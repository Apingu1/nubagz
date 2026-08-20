from decimal import Decimal
import json
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import User, Project, Campaign, Enrollment, WalletConnection
from ..risk_models import UserTrustProfile
from ..integration_models import GasSponsorshipBudget, GasSponsorshipRequest

router = APIRouter(prefix="/api/gas", tags=["sponsored-gas"])
SUPPORTED = {"avalanche":"AVAX","ethereum":"ETH","base":"ETH","arbitrum":"ETH","polygon":"POL"}
CHAIN_IDS = {"avalanche":43114,"ethereum":1,"base":8453,"arbitrum":42161,"polygon":137}


class BudgetIn(BaseModel):
    project_id: int
    chain: str = Field(min_length=2, max_length=32)
    amount_per_tx: Decimal = Field(gt=0)
    max_transactions: int = Field(gt=0, le=100000)
    funded_amount: Decimal = Field(gt=0)
    funding_reference: str = Field(min_length=4, max_length=255)


class FundingVerifyIn(BaseModel):
    funded_amount: Decimal = Field(gt=0)
    funding_reference: str = Field(min_length=4, max_length=255)


class RequestIn(BaseModel):
    campaign_id: int
    transaction: dict


def maximum_obligation(row: GasSponsorshipBudget) -> Decimal:
    return Decimal(row.amount_per_tx) * Decimal(row.max_transactions)


def budget_payload(row: GasSponsorshipBudget, db: Session, include_funding_reference: bool = False):
    project = db.get(Project, row.project_id)
    remaining = max(0, row.max_transactions-row.executed_transactions)
    payload = {
        "id":row.id,"project_id":row.project_id,"project_name":project.name if project else None,
        "chain":row.chain,"native_asset":row.native_asset,"amount_per_tx":str(row.amount_per_tx),
        "max_transactions":row.max_transactions,"executed_transactions":row.executed_transactions,
        "remaining_transactions":remaining,"funded_amount":str(row.funded_amount),"spent_amount":str(row.spent_amount),
        "remaining_funded_amount":str(max(Decimal("0"),Decimal(row.funded_amount)-Decimal(row.spent_amount))),
        "maximum_obligation":str(maximum_obligation(row)),"funding_status":row.funding_status,"status":row.status,
        "created_at":row.created_at.isoformat(),
    }
    if include_funding_reference:
        payload["funding_reference"] = row.funding_reference
    return payload


def request_payload(row: GasSponsorshipRequest, db: Session):
    budget = db.get(GasSponsorshipBudget,row.budget_id);campaign = db.get(Campaign,row.campaign_id)
    return {"id":row.id,"budget_id":row.budget_id,"campaign_id":row.campaign_id,"campaign_title":campaign.title if campaign else None,"chain":budget.chain if budget else None,"max_sponsored_native":str(budget.amount_per_tx) if budget else None,"status":row.status,"provider":row.provider_name,"provider_request_id":row.provider_request_id,"tx_hash":row.tx_hash,"gas_spent_native":str(row.gas_spent_native) if row.gas_spent_native is not None else None,"created_at":row.created_at.isoformat()}


def verified_wallet(db:Session,user:User):
    wallet=db.query(WalletConnection).filter(WalletConnection.user_id==user.id,WalletConnection.verified_at.isnot(None)).order_by(WalletConnection.is_primary.desc(),WalletConnection.verified_at.desc()).first()
    if not wallet: raise HTTPException(400,"Connect and verify an EVM wallet before requesting sponsored gas")
    return wallet


def valid_evm_address(value: object) -> bool:
    if not isinstance(value,str) or len(value)!=42 or not value.startswith("0x"): return False
    try: int(value[2:],16); return True
    except ValueError: return False


def validate_transaction(tx: dict, chain: str):
    if not isinstance(tx,dict) or not valid_evm_address(tx.get("to")):
        raise HTTPException(400,"Sponsored transaction must include a valid EVM destination address")
    data=tx.get("data","0x")
    if not isinstance(data,str) or not data.startswith("0x"):
        raise HTTPException(400,"Sponsored transaction data must be hex encoded")
    value=tx.get("value","0x0")
    if not isinstance(value,str) or not value.startswith("0x"):
        raise HTTPException(400,"Sponsored transaction value must be hex encoded")
    try:
        int(value,16)
        if len(data)>2: int(data[2:],16)
    except ValueError as exc:
        raise HTTPException(400,"Sponsored transaction contains invalid hex data") from exc
    if len(json.dumps(tx,separators=(",",":")))>20000:
        raise HTTPException(400,"Sponsored transaction payload is too large")
    raw_chain=tx.get("chainId")
    if raw_chain is not None:
        try: chain_id=int(raw_chain,0) if isinstance(raw_chain,str) else int(raw_chain)
        except (TypeError,ValueError) as exc: raise HTTPException(400,"Sponsored transaction chainId is invalid") from exc
        if chain_id!=CHAIN_IDS[chain.strip().lower()]: raise HTTPException(400,"Sponsored transaction chainId does not match the gas budget chain")


def valid_tx_hash(value: object) -> bool:
    if not isinstance(value,str) or len(value)!=66 or not value.startswith("0x"): return False
    try: int(value[2:],16); return True
    except ValueError: return False


@router.get("/status")
def provider_status(_:User=Depends(get_current_user)):
    configured=bool(settings.gas_sponsor_provider_base_url)
    return {"configured":configured,"mode":"PROVIDER_BACKED" if configured else "DRAFT_ONLY","principle":"NuBagz spends only independently verified project-sponsored gas inventory after a configured provider returns an actual transaction hash. Founder funds are never used as fallback gas."}


@router.get("/budgets")
def live_budgets(db:Session=Depends(get_db),_:User=Depends(get_current_user)):
    rows=db.query(GasSponsorshipBudget).filter(GasSponsorshipBudget.status=="LIVE",GasSponsorshipBudget.funding_status=="VERIFIED").order_by(GasSponsorshipBudget.created_at.desc()).all()
    return [budget_payload(r,db) for r in rows if r.executed_transactions<r.max_transactions and Decimal(r.spent_amount)<Decimal(r.funded_amount)]


@router.get("/budgets/mine")
def my_budgets(db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    rows=db.query(GasSponsorshipBudget).filter(GasSponsorshipBudget.created_by_id==user.id).order_by(GasSponsorshipBudget.created_at.desc()).all()
    return [budget_payload(r,db,include_funding_reference=True) for r in rows]


@router.get("/budgets/admin")
def admin_budgets(db:Session=Depends(get_db),_:User=Depends(require_admin)):
    return [budget_payload(r,db,include_funding_reference=True) for r in db.query(GasSponsorshipBudget).order_by(GasSponsorshipBudget.created_at.desc()).all()]


@router.post("/budgets")
def create_budget(data:BudgetIn,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    project=db.get(Project,data.project_id)
    if not project or project.owner_id!=user.id: raise HTTPException(404,"Project not found")
    if project.status!="APPROVED": raise HTTPException(400,"Project must be approved before sponsoring gas")
    chain=data.chain.strip().lower()
    if chain not in SUPPORTED: raise HTTPException(400,"Unsupported EVM chain")
    required=data.amount_per_tx*Decimal(data.max_transactions)
    if data.funded_amount<required: raise HTTPException(400,f"Gas funding must cover the maximum obligation of {required} {SUPPORTED[chain]}")
    row=GasSponsorshipBudget(project_id=project.id,created_by_id=user.id,chain=chain.title(),native_asset=SUPPORTED[chain],amount_per_tx=data.amount_per_tx,max_transactions=data.max_transactions,funded_amount=data.funded_amount,funding_reference=data.funding_reference.strip())
    db.add(row);db.commit();db.refresh(row);return budget_payload(row,db,include_funding_reference=True)


@router.post("/budgets/{budget_id}/activate")
def activate_budget(budget_id:int,data:FundingVerifyIn,db:Session=Depends(get_db),_:User=Depends(require_admin)):
    row=db.query(GasSponsorshipBudget).filter(GasSponsorshipBudget.id==budget_id).with_for_update().first()
    if not row: raise HTTPException(404,"Gas budget not found")
    if row.status!="PENDING" or row.funding_status=="VERIFIED": raise HTTPException(409,"Gas budget funding has already been reviewed")
    required=maximum_obligation(row)
    if data.funded_amount<required: raise HTTPException(400,f"Verified gas funding must cover the maximum obligation of {required} {row.native_asset}")
    row.funded_amount=data.funded_amount;row.funding_reference=data.funding_reference.strip();row.funding_status="VERIFIED";row.status="LIVE";db.commit();return budget_payload(row,db,include_funding_reference=True)


@router.get("/requests")
def my_requests(db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    return [request_payload(r,db) for r in db.query(GasSponsorshipRequest).filter(GasSponsorshipRequest.user_id==user.id).order_by(GasSponsorshipRequest.created_at.desc()).all()]


@router.post("/budgets/{budget_id}/requests")
def create_request(budget_id:int,data:RequestIn,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    trust=db.query(UserTrustProfile).filter(UserTrustProfile.user_id==user.id).first()
    if trust and trust.trust_level=="RESTRICTED": raise HTTPException(403,"This account is restricted from sponsored gas pending trust review")
    budget=db.get(GasSponsorshipBudget,budget_id);campaign=db.get(Campaign,data.campaign_id)
    if not budget or budget.status!="LIVE" or budget.funding_status!="VERIFIED": raise HTTPException(404,"Live sponsored gas budget not found")
    if not campaign or campaign.project_id!=budget.project_id or campaign.status!="LIVE": raise HTTPException(400,"Sponsored gas must be attached to a live campaign from the sponsoring project")
    enrollment=db.query(Enrollment).filter(Enrollment.user_id==user.id,Enrollment.campaign_id==campaign.id).first()
    if not enrollment: raise HTTPException(403,"Join the sponsoring Bag before requesting its gas allowance")
    if budget.executed_transactions>=budget.max_transactions or Decimal(budget.spent_amount)>=Decimal(budget.funded_amount): raise HTTPException(409,"Sponsored gas budget is exhausted")
    existing=db.query(GasSponsorshipRequest).filter(GasSponsorshipRequest.budget_id==budget.id,GasSponsorshipRequest.user_id==user.id).first()
    if existing: return request_payload(existing,db)
    validate_transaction(data.transaction,budget.chain)
    wallet=verified_wallet(db,user)
    row=GasSponsorshipRequest(budget_id=budget.id,campaign_id=campaign.id,user_id=user.id,wallet_connection_id=wallet.id,transaction_payload=json.dumps(data.transaction,separators=(",", ":")))
    db.add(row);db.commit();db.refresh(row);return request_payload(row,db)


@router.post("/requests/{request_id}/execute")
def execute_request(request_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    request=db.query(GasSponsorshipRequest).filter(GasSponsorshipRequest.id==request_id,GasSponsorshipRequest.user_id==user.id).with_for_update().first()
    if not request: raise HTTPException(404,"Sponsored gas request not found")
    if request.status=="EXECUTED": return request_payload(request,db)
    trust=db.query(UserTrustProfile).filter(UserTrustProfile.user_id==user.id).first()
    if trust and trust.trust_level=="RESTRICTED": raise HTTPException(403,"This account is restricted from sponsored gas pending trust review")
    if not settings.gas_sponsor_provider_base_url: raise HTTPException(503,"Gas sponsorship provider is not configured. The request remains a draft and no sponsor budget was spent.")
    budget=db.query(GasSponsorshipBudget).filter(GasSponsorshipBudget.id==request.budget_id).with_for_update().first();wallet=db.get(WalletConnection,request.wallet_connection_id);campaign=db.get(Campaign,request.campaign_id)
    enrollment=db.query(Enrollment).filter(Enrollment.user_id==user.id,Enrollment.campaign_id==request.campaign_id).first()
    if not budget or budget.status!="LIVE" or budget.funding_status!="VERIFIED" or not wallet or wallet.user_id!=user.id or not wallet.verified_at or not campaign or campaign.status!="LIVE" or not enrollment: raise HTTPException(409,"Sponsored gas request is no longer eligible")
    if budget.executed_transactions>=budget.max_transactions: raise HTTPException(409,"Sponsored gas transaction allocation is exhausted")
    remaining=Decimal(budget.funded_amount)-Decimal(budget.spent_amount)
    if remaining<=0: raise HTTPException(409,"Sponsored gas funding is exhausted")
    cap=min(Decimal(budget.amount_per_tx),remaining)
    transaction=json.loads(request.transaction_payload);validate_transaction(transaction,budget.chain)
    url=settings.gas_sponsor_provider_base_url.rstrip("/")+"/sponsor";headers={"Content-Type":"application/json"}
    if settings.gas_sponsor_provider_api_key: headers["Authorization"]=f"Bearer {settings.gas_sponsor_provider_api_key}"
    payload={"wallet_address":wallet.address,"chain":budget.chain,"max_native_amount":str(cap),"transaction":transaction}
    try:
        response=httpx.post(url,json=payload,headers=headers,timeout=15.0);response.raise_for_status();out=response.json()
    except Exception as exc: raise HTTPException(502,"Gas sponsorship provider request failed; no sponsor budget was spent") from exc
    tx_hash=out.get("tx_hash");spent=out.get("gas_spent_native")
    if not valid_tx_hash(tx_hash) or spent is None: raise HTTPException(502,"Gas sponsorship provider returned an incomplete or invalid execution result")
    try: spent_amount=Decimal(str(spent))
    except Exception as exc: raise HTTPException(502,"Gas sponsorship provider returned an invalid gas amount") from exc
    if spent_amount<=0 or spent_amount>cap: raise HTTPException(502,"Gas sponsorship provider reported spend outside the verified budget cap")
    request.status="EXECUTED";request.provider_name=out.get("provider") or "configured-provider";request.provider_request_id=str(out.get("request_id")) if out.get("request_id") is not None else None;request.tx_hash=str(tx_hash);request.gas_spent_native=spent_amount
    budget.spent_amount=Decimal(budget.spent_amount)+spent_amount;budget.executed_transactions+=1
    if budget.executed_transactions>=budget.max_transactions or Decimal(budget.spent_amount)>=Decimal(budget.funded_amount): budget.status="COMPLETED"
    db.commit();return request_payload(request,db)
