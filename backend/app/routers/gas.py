from datetime import datetime, timedelta, UTC
from decimal import Decimal
import json
import secrets
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import User, Project, Campaign, Enrollment, WalletConnection
from ..challenge_models import Challenge
from ..economy_models import CampaignFunding, CampaignAccessRule
from ..integration_models import GasSponsorshipPolicy, GasSponsorshipClaim
from ..economy import campaign_distributed_total
from .risk import evaluate_user

router = APIRouter(prefix="/api/gas", tags=["sponsored-gas"])
SUPPORTED = {"avalanche":"AVAX","ethereum":"ETH","base":"ETH","arbitrum":"ETH","polygon":"POL"}
CHAIN_IDS = {"avalanche":43114,"ethereum":1,"base":8453,"arbitrum":42161,"polygon":137}
ACTIVE_CLAIM_STATUSES = {"RESERVED", "EXECUTED"}


class FundingVerifyIn(BaseModel):
    funded_amount: Decimal = Field(gt=0)
    funding_reference: str = Field(min_length=4, max_length=255)


class PolicyStatusIn(BaseModel):
    status: str


class PrepareIn(BaseModel):
    # Kept as an object for forward compatibility. The sponsored transaction is
    # constructed from the creator-approved challenge config, never from arbitrary user calldata.
    pass


def _valid_evm_address(value: object) -> bool:
    if not isinstance(value,str) or len(value)!=42 or not value.startswith("0x"): return False
    try: int(value[2:],16); return True
    except ValueError: return False


def _valid_tx_hash(value: object) -> bool:
    if not isinstance(value,str) or len(value)!=66 or not value.startswith("0x"): return False
    try: int(value[2:],16); return True
    except ValueError: return False


def _verified_wallet(db: Session, user: User):
    wallet = db.query(WalletConnection).filter(WalletConnection.user_id==user.id,WalletConnection.verified_at.isnot(None)).order_by(WalletConnection.is_primary.desc(),WalletConnection.verified_at.desc()).first()
    if not wallet: raise HTTPException(400,"Connect and verify an EVM wallet before using sponsored gas")
    return wallet


def _release_expired(db: Session, policy_id: int):
    now = datetime.now(UTC)
    rows = db.query(GasSponsorshipClaim).filter(GasSponsorshipClaim.policy_id==policy_id,GasSponsorshipClaim.status=="RESERVED",GasSponsorshipClaim.reservation_expires_at < now).all()
    for row in rows: row.status = "RELEASED"
    if rows: db.flush()


def _claim_counts(db: Session, policy: GasSponsorshipPolicy, user_id: int):
    _release_expired(db, policy.id)
    total = db.query(func.count(GasSponsorshipClaim.id)).filter(GasSponsorshipClaim.policy_id==policy.id,GasSponsorshipClaim.status.in_(ACTIVE_CLAIM_STATUSES)).scalar() or 0
    user_claims = db.query(func.count(GasSponsorshipClaim.id)).filter(GasSponsorshipClaim.policy_id==policy.id,GasSponsorshipClaim.user_id==user_id,GasSponsorshipClaim.status.in_(ACTIVE_CLAIM_STATUSES)).scalar() or 0
    unique_users = db.query(func.count(func.distinct(GasSponsorshipClaim.user_id))).filter(GasSponsorshipClaim.policy_id==policy.id,GasSponsorshipClaim.status.in_(ACTIVE_CLAIM_STATUSES)).scalar() or 0
    user_already_counted = user_claims > 0
    reserved = db.query(func.coalesce(func.sum(GasSponsorshipClaim.reserved_native_amount),0)).filter(GasSponsorshipClaim.policy_id==policy.id,GasSponsorshipClaim.status=="RESERVED").scalar() or Decimal("0")
    return int(total), int(user_claims), int(unique_users), user_already_counted, Decimal(reserved)


def _policy_reason(db: Session, policy: GasSponsorshipPolicy, user_id: int):
    now = datetime.now(UTC)
    if policy.funding_status != "VERIFIED": return "FUNDING_NOT_VERIFIED", Decimal("0")
    if policy.status == "PAUSED": return "SPONSORSHIP_PAUSED", Decimal("0")
    if policy.status in {"EXHAUSTED","EXPIRED","COMPLETED"}: return policy.status, Decimal("0")
    if policy.status != "ACTIVE": return "SPONSORSHIP_UNAVAILABLE", Decimal("0")
    if policy.starts_at and policy.starts_at > now: return "SPONSORSHIP_NOT_STARTED", Decimal("0")
    if policy.ends_at and policy.ends_at < now:
        policy.status = "EXPIRED"; return "SPONSORSHIP_EXPIRED", Decimal("0")
    total,user_claims,unique_users,user_counted,reserved = _claim_counts(db,policy,user_id)
    if total >= policy.max_claims:
        policy.status = "EXHAUSTED"; return "CLAIM_LIMIT_REACHED", Decimal("0")
    if user_claims >= policy.max_claims_per_wallet: return "WALLET_LIMIT_REACHED", Decimal("0")
    if policy.max_unique_users is not None and not user_counted and unique_users >= policy.max_unique_users: return "USER_LIMIT_REACHED", Decimal("0")
    remaining = Decimal(policy.funded_amount) - Decimal(policy.spent_amount) - reserved
    if remaining <= 0:
        policy.status = "EXHAUSTED"; return "BUDGET_EXHAUSTED", Decimal("0")
    return None, min(Decimal(policy.max_native_per_claim), remaining)


def _build_transaction(challenge: Challenge, chain: str):
    config = dict(challenge.config or {})
    target = str(config.get("target_address") or challenge.target_id or "").strip()
    if not _valid_evm_address(target): raise HTTPException(409,"This sponsored activity does not have a valid configured target contract/address")
    data = str(config.get("calldata") or "0x").strip()
    if not data.startswith("0x"):
        raise HTTPException(409,"This sponsored activity has invalid configured transaction data")
    try:
        if len(data)>2: int(data[2:],16)
    except ValueError as exc: raise HTTPException(409,"This sponsored activity has invalid configured transaction data") from exc
    raw_value = config.get("value_wei",0)
    try: value_int = int(str(raw_value),0) if isinstance(raw_value,str) else int(raw_value)
    except (TypeError,ValueError) as exc: raise HTTPException(409,"This sponsored activity has invalid configured transaction value") from exc
    if value_int < 0: raise HTTPException(409,"This sponsored activity has invalid configured transaction value")
    chain_id = CHAIN_IDS[chain.strip().lower()]
    return {"to":target,"data":data,"value":hex(value_int),"chainId":chain_id}


def _ensure_enrollment(db: Session, user: User, campaign: Campaign):
    existing = db.query(Enrollment).filter(Enrollment.user_id==user.id,Enrollment.campaign_id==campaign.id).first()
    if existing: return existing
    funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id==campaign.id,CampaignFunding.status=="VERIFIED").first()
    distributed = campaign_distributed_total(db,campaign.id)
    if not funding or Decimal(funding.verified_amount)-distributed < Decimal(campaign.gross_reward_per_user):
        raise HTTPException(409,"This Bag does not currently have enough verified reward inventory")
    trust = evaluate_user(db,user)
    if trust.trust_level == "RESTRICTED": raise HTTPException(403,"This account is restricted from sponsored gas pending trust review")
    access = db.query(CampaignAccessRule).filter(CampaignAccessRule.campaign_id==campaign.id).first()
    if access and user.bag_score < access.min_bag_score: raise HTTPException(403,f"BagScore {access.min_bag_score}+ required for this opportunity")
    enrolled_count = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id==campaign.id).scalar() or 0
    if enrolled_count >= campaign.max_users: raise HTTPException(409,"This Bag is full")
    row = Enrollment(user_id=user.id,campaign_id=campaign.id); db.add(row); db.flush(); return row


def _policy_payload(row: GasSponsorshipPolicy, db: Session):
    project = db.get(Project,row.project_id); challenge = db.get(Challenge,row.challenge_id); campaign = db.get(Campaign,challenge.campaign_id) if challenge else None
    total = db.query(func.count(GasSponsorshipClaim.id)).filter(GasSponsorshipClaim.policy_id==row.id,GasSponsorshipClaim.status=="EXECUTED").scalar() or 0
    reserved = db.query(func.count(GasSponsorshipClaim.id)).filter(GasSponsorshipClaim.policy_id==row.id,GasSponsorshipClaim.status=="RESERVED").scalar() or 0
    unique = db.query(func.count(func.distinct(GasSponsorshipClaim.user_id))).filter(GasSponsorshipClaim.policy_id==row.id,GasSponsorshipClaim.status.in_(ACTIVE_CLAIM_STATUSES)).scalar() or 0
    return {"id":row.id,"challenge_id":row.challenge_id,"challenge_title":challenge.title if challenge else None,"campaign_id":campaign.id if campaign else None,"campaign_title":campaign.title if campaign else None,"project_id":row.project_id,"project_name":project.name if project else None,"chain":row.chain,"native_asset":row.native_asset,"max_native_per_claim":str(row.max_native_per_claim),"max_unique_users":row.max_unique_users,"max_claims":row.max_claims,"max_claims_per_wallet":row.max_claims_per_wallet,"funded_amount":str(row.funded_amount),"spent_amount":str(row.spent_amount),"remaining_funded_amount":str(max(Decimal("0"),Decimal(row.funded_amount)-Decimal(row.spent_amount))),"executed_claims":int(total),"reserved_claims":int(reserved),"unique_users":int(unique),"funding_reference":row.funding_reference,"funding_status":row.funding_status,"status":row.status,"starts_at":row.starts_at.isoformat() if row.starts_at else None,"ends_at":row.ends_at.isoformat() if row.ends_at else None}


def _claim_payload(row: GasSponsorshipClaim, db: Session, mode: str = "SPONSORED"):
    policy = db.get(GasSponsorshipPolicy,row.policy_id); challenge = db.get(Challenge,row.challenge_id)
    return {"mode":mode,"claim_id":row.id,"challenge_id":row.challenge_id,"challenge_title":challenge.title if challenge else None,"status":row.status,"chain":policy.chain if policy else None,"native_asset":policy.native_asset if policy else None,"reserved_native_amount":str(row.reserved_native_amount),"transaction":json.loads(row.transaction_payload),"reservation_expires_at":row.reservation_expires_at.isoformat(),"tx_hash":row.tx_hash,"gas_spent_native":str(row.gas_spent_native) if row.gas_spent_native is not None else None}


@router.get("/status")
def provider_status(_:User=Depends(get_current_user)):
    configured=bool(settings.gas_sponsor_provider_base_url)
    return {"configured":configured,"mode":"PROVIDER_BACKED" if configured else "DRAFT_ONLY","principle":"Gas Pass is optional project-funded sponsorship attached to specific on-chain Bag Work. When sponsorship is unavailable, the activity remains available with normal user-paid network gas."}


@router.get("/policies/mine")
def my_policies(db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    rows=db.query(GasSponsorshipPolicy).filter(GasSponsorshipPolicy.created_by_id==user.id).order_by(GasSponsorshipPolicy.created_at.desc()).all()
    return [_policy_payload(r,db) for r in rows]


@router.get("/policies/admin")
def admin_policies(db:Session=Depends(get_db),_:User=Depends(require_admin)):
    return [_policy_payload(r,db) for r in db.query(GasSponsorshipPolicy).order_by(GasSponsorshipPolicy.created_at.desc()).all()]


@router.post("/policies/{policy_id}/verify")
def verify_policy(policy_id:int,data:FundingVerifyIn,db:Session=Depends(get_db),_:User=Depends(require_admin)):
    row=db.query(GasSponsorshipPolicy).filter(GasSponsorshipPolicy.id==policy_id).with_for_update().first()
    if not row: raise HTTPException(404,"Gas Pass policy not found")
    required=Decimal(row.max_native_per_claim)*Decimal(row.max_claims)
    if data.funded_amount < required: raise HTTPException(400,f"Verified gas funding must cover the maximum configured obligation of {required} {row.native_asset}")
    row.funded_amount=data.funded_amount; row.funding_reference=data.funding_reference.strip(); row.funding_status="VERIFIED"; row.status="ACTIVE"; db.commit()
    return _policy_payload(row,db)


@router.post("/policies/{policy_id}/status")
def set_policy_status(policy_id:int,data:PolicyStatusIn,db:Session=Depends(get_db),admin:User=Depends(require_admin)):
    row=db.query(GasSponsorshipPolicy).filter(GasSponsorshipPolicy.id==policy_id).with_for_update().first()
    if not row: raise HTTPException(404,"Gas Pass policy not found")
    status=data.status.upper()
    if status not in {"ACTIVE","PAUSED"}: raise HTTPException(400,"Gas Pass status must be ACTIVE or PAUSED")
    if status=="ACTIVE" and row.funding_status!="VERIFIED": raise HTTPException(409,"Verify gas funding before activating sponsorship")
    row.status=status; db.commit(); return _policy_payload(row,db)


@router.get("/challenges/{challenge_id}")
def challenge_gas_status(challenge_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    challenge=db.get(Challenge,challenge_id)
    if not challenge or challenge.category!="ONCHAIN": raise HTTPException(404,"On-chain Bag Work not found")
    policy=db.query(GasSponsorshipPolicy).filter(GasSponsorshipPolicy.challenge_id==challenge_id).first()
    if not policy: return {"enabled":False,"mode":"USER_PAID","reason":"NO_SPONSORSHIP"}
    policy=db.query(GasSponsorshipPolicy).filter(GasSponsorshipPolicy.id==policy.id).with_for_update().first()
    reason,cap=_policy_reason(db,policy,user.id); db.commit()
    return {"enabled":True,"mode":"USER_PAID" if reason else "SPONSORED","reason":reason,"max_sponsored_native":str(cap),"policy":_policy_payload(policy,db)}


@router.post("/challenges/{challenge_id}/prepare")
def prepare_sponsorship(challenge_id:int,_:PrepareIn,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    challenge=db.get(Challenge,challenge_id); campaign=db.get(Campaign,challenge.campaign_id) if challenge else None; project=db.get(Project,campaign.project_id) if campaign else None
    if not challenge or challenge.category!="ONCHAIN" or challenge.status!="ACTIVE" or not campaign or campaign.status!="LIVE" or not project or project.status in {"SUSPENDED","ARCHIVED"}: raise HTTPException(404,"Live on-chain Bag Work not found")
    transaction=_build_transaction(challenge,str((challenge.config or {}).get("chain") or project.chain))
    policy=db.query(GasSponsorshipPolicy).filter(GasSponsorshipPolicy.challenge_id==challenge.id).with_for_update().first()
    if not policy: return {"mode":"USER_PAID","reason":"NO_SPONSORSHIP","transaction":transaction}
    _ensure_enrollment(db,user,campaign)
    wallet=_verified_wallet(db,user)
    reason,cap=_policy_reason(db,policy,user.id)
    if reason:
        db.commit(); return {"mode":"USER_PAID","reason":reason,"transaction":transaction}
    existing=db.query(GasSponsorshipClaim).filter(GasSponsorshipClaim.policy_id==policy.id,GasSponsorshipClaim.user_id==user.id,GasSponsorshipClaim.status=="RESERVED").order_by(GasSponsorshipClaim.created_at.desc()).first()
    if existing and existing.reservation_expires_at>=datetime.now(UTC):
        db.commit(); return _claim_payload(existing,db)
    row=GasSponsorshipClaim(policy_id=policy.id,challenge_id=challenge.id,campaign_id=campaign.id,user_id=user.id,wallet_connection_id=wallet.id,reservation_key=secrets.token_urlsafe(32),transaction_payload=json.dumps(transaction,separators=(",",":")),reserved_native_amount=cap,status="RESERVED",reservation_expires_at=datetime.now(UTC)+timedelta(minutes=10))
    db.add(row); db.commit(); db.refresh(row); return _claim_payload(row,db)


@router.post("/claims/{claim_id}/execute")
def execute_sponsorship(claim_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    claim=db.query(GasSponsorshipClaim).filter(GasSponsorshipClaim.id==claim_id,GasSponsorshipClaim.user_id==user.id).with_for_update().first()
    if not claim: raise HTTPException(404,"Gas Pass reservation not found")
    if claim.status=="EXECUTED": return _claim_payload(claim,db)
    if claim.status!="RESERVED" or claim.reservation_expires_at<datetime.now(UTC):
        claim.status="RELEASED"; db.commit(); raise HTTPException(409,"Gas Pass reservation expired. Prepare the activity again; normal user-paid gas remains available.")
    if not settings.gas_sponsor_provider_base_url: raise HTTPException(503,"Gas sponsorship provider is not configured. No project gas budget was spent.")
    policy=db.query(GasSponsorshipPolicy).filter(GasSponsorshipPolicy.id==claim.policy_id).with_for_update().first(); challenge=db.get(Challenge,claim.challenge_id); campaign=db.get(Campaign,claim.campaign_id); wallet=db.get(WalletConnection,claim.wallet_connection_id)
    if not policy or policy.status!="ACTIVE" or policy.funding_status!="VERIFIED" or not challenge or challenge.status!="ACTIVE" or not campaign or campaign.status!="LIVE" or not wallet or wallet.user_id!=user.id or not wallet.verified_at: raise HTTPException(409,"This Gas Pass reservation is no longer eligible")
    transaction=_build_transaction(challenge,policy.chain)
    if transaction != json.loads(claim.transaction_payload): raise HTTPException(409,"The Bag Work transaction changed after this Gas Pass reservation was created")
    remaining=Decimal(policy.funded_amount)-Decimal(policy.spent_amount)
    cap=min(Decimal(claim.reserved_native_amount),remaining)
    if cap<=0: policy.status="EXHAUSTED"; db.commit(); raise HTTPException(409,"Project-sponsored gas has been exhausted. Normal user-paid gas remains available.")
    url=settings.gas_sponsor_provider_base_url.rstrip("/")+"/sponsor"; headers={"Content-Type":"application/json","Idempotency-Key":claim.reservation_key}
    if settings.gas_sponsor_provider_api_key: headers["Authorization"]=f"Bearer {settings.gas_sponsor_provider_api_key}"
    payload={"wallet_address":wallet.address,"chain":policy.chain,"max_native_amount":str(cap),"transaction":transaction,"reservation_key":claim.reservation_key}
    try:
        response=httpx.post(url,json=payload,headers=headers,timeout=15.0); response.raise_for_status(); out=response.json()
    except Exception as exc: raise HTTPException(502,"Gas sponsorship provider request failed; no project gas budget was spent") from exc
    tx_hash=out.get("tx_hash"); spent=out.get("gas_spent_native")
    if not _valid_tx_hash(tx_hash) or spent is None: raise HTTPException(502,"Gas sponsorship provider returned an incomplete execution result")
    try: spent_amount=Decimal(str(spent))
    except Exception as exc: raise HTTPException(502,"Gas sponsorship provider returned an invalid gas amount") from exc
    if spent_amount<=0 or spent_amount>cap: raise HTTPException(502,"Gas sponsorship provider reported spend outside the reserved project budget cap")
    claim.status="EXECUTED"; claim.provider_name=out.get("provider") or "configured-provider"; claim.provider_request_id=str(out.get("request_id")) if out.get("request_id") is not None else None; claim.tx_hash=str(tx_hash); claim.gas_spent_native=spent_amount
    policy.spent_amount=Decimal(policy.spent_amount)+spent_amount
    reason,_=_policy_reason(db,policy,user.id)
    if reason in {"CLAIM_LIMIT_REACHED","BUDGET_EXHAUSTED","USER_LIMIT_REACHED"}: policy.status="EXHAUSTED"
    db.commit(); return _claim_payload(claim,db)
