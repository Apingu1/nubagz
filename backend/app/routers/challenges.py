from datetime import datetime, UTC
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import Campaign, Enrollment, LedgerEntry, Project, User, WalletConnection
from ..challenge_models import Challenge, ChallengeCompletion, ChallengeOnchainProof, SocialAccount
from ..economy_models import CampaignAccessRule, CampaignFunding
from ..integration_models import GasSponsorshipPolicy
from ..engagement_models import ReferralConversion
from ..economy import campaign_distributed_total
from ..schemas import ChallengeCompleteIn, ChallengeDecisionIn
from ..x_verifier import XVerificationUnavailable, make_x_proof_code, verify_x_post_proof
from .onchain import rpc_call
from .risk import evaluate_user

router = APIRouter(prefix="/api/challenges", tags=["bag-work"])
REFERRAL_ELIGIBLE_LEVELS = {"NORMAL", "VERIFIED"}
VERIFIED_STATUSES = {"VERIFIED", "APPROVED"}
PUBLIC_PROJECT_STATUSES = {"LIVE", "APPROVED"}
SUPPORTED_EVM_CHAINS = {"avalanche", "ethereum", "base", "arbitrum", "polygon"}


def _as_utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _valid_tx_hash(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        return False
    try:
        int(value[2:], 16)
        return True
    except ValueError:
        return False


def _funding_available(db: Session, campaign: Campaign, next_gross: Decimal = Decimal("0")) -> bool:
    funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign.id, CampaignFunding.status == "VERIFIED").first()
    if not funding:
        return False
    distributed = campaign_distributed_total(db, campaign.id)
    return Decimal(funding.verified_amount) - distributed >= next_gross


def _ensure_enrollment(db: Session, user: User, campaign: Campaign) -> Enrollment:
    enrollment = db.query(Enrollment).filter(Enrollment.user_id == user.id, Enrollment.campaign_id == campaign.id).first()
    if enrollment:
        return enrollment
    if not _funding_available(db, campaign, Decimal(campaign.gross_reward_per_user)):
        raise HTTPException(409, "This Bag is temporarily unavailable because verified reward inventory is exhausted")
    trust = evaluate_user(db, user)
    if trust.trust_level == "RESTRICTED":
        raise HTTPException(403, "This account is restricted from new reward opportunities pending trust review")
    access_rule = db.query(CampaignAccessRule).filter(CampaignAccessRule.campaign_id == campaign.id).first()
    if access_rule and user.bag_score < access_rule.min_bag_score:
        raise HTTPException(403, f"BagScore {access_rule.min_bag_score}+ required for this opportunity")
    enrolled_count = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == campaign.id).scalar() or 0
    if enrolled_count >= campaign.max_users:
        raise HTTPException(409, "This Bag is full")
    enrollment = Enrollment(user_id=user.id, campaign_id=campaign.id)
    db.add(enrollment)
    db.flush()
    return enrollment


def _settle_campaign(db: Session, user: User, campaign: Campaign, enrollment: Enrollment) -> None:
    gross = Decimal(campaign.gross_reward_per_user)
    if not _funding_available(db, campaign, gross):
        raise HTTPException(409, "Reward inventory was exhausted before this Bag could settle")
    referrer_profile = None
    if user.referred_by_id:
        referrer = db.get(User, user.referred_by_id)
        if referrer:
            referrer_profile = evaluate_user(db, referrer)
    user_amount = gross * Decimal(campaign.user_share_pct) / Decimal("100")
    platform_amount = gross * Decimal(campaign.nubagz_share_pct) / Decimal("100")
    referral_amount = gross * Decimal(campaign.referral_share_pct) / Decimal("100")
    enrollment.status = "COMPLETED"
    enrollment.completed_at = datetime.now(UTC)
    enrollment.earned_amount = user_amount
    db.add(LedgerEntry(user_id=user.id, campaign_id=campaign.id, asset_symbol=campaign.reward_asset, amount=user_amount, entry_type="CAMPAIGN_REWARD", note=f"Completed {campaign.title}"))
    db.add(LedgerEntry(user_id=None, campaign_id=campaign.id, asset_symbol=campaign.reward_asset, amount=platform_amount, entry_type="PLATFORM_SHARE", note="NuBagz campaign share"))
    if user.referred_by_id and referral_amount > 0:
        referrer_level = referrer_profile.trust_level if referrer_profile else "REVIEW"
        if referrer_level not in REFERRAL_ELIGIBLE_LEVELS:
            db.add(LedgerEntry(user_id=None, campaign_id=campaign.id, asset_symbol=campaign.reward_asset, amount=referral_amount, entry_type="COMMUNITY_SHARE", note=f"Referral share redirected because referrer trust is {referrer_level}"))
            db.add(ReferralConversion(referrer_id=user.referred_by_id, referred_user_id=user.id, campaign_id=campaign.id, asset_symbol=campaign.reward_asset, allocated_amount=referral_amount, paid_amount=0, status="REDIRECTED", reason=f"Referrer {referrer_level.lower()} at settlement"))
        else:
            db.add(LedgerEntry(user_id=user.referred_by_id, campaign_id=campaign.id, asset_symbol=campaign.reward_asset, amount=referral_amount, entry_type="REFERRAL_SHARE", note=f"Referral reward from {user.username}"))
            db.add(ReferralConversion(referrer_id=user.referred_by_id, referred_user_id=user.id, campaign_id=campaign.id, asset_symbol=campaign.reward_asset, allocated_amount=referral_amount, paid_amount=referral_amount, status="PAID", reason="Funded campaign conversion"))
    else:
        db.add(LedgerEntry(user_id=None, campaign_id=campaign.id, asset_symbol=campaign.reward_asset, amount=referral_amount, entry_type="COMMUNITY_SHARE", note="Unassigned referral share"))
    user.bag_score = min(1000, user.bag_score + 20)


def _finalize_completion(db: Session, user: User, campaign: Campaign, challenge: Challenge, completion: ChallengeCompletion, status: str, evidence: dict | None = None) -> bool:
    enrollment = _ensure_enrollment(db, user, campaign)
    other_verified = db.query(func.count(ChallengeCompletion.id)).join(Challenge, Challenge.id == ChallengeCompletion.challenge_id).filter(ChallengeCompletion.user_id == user.id, Challenge.campaign_id == campaign.id, ChallengeCompletion.id != completion.id, ChallengeCompletion.status.in_(VERIFIED_STATUSES)).scalar() or 0
    total = db.query(func.count(Challenge.id)).filter(Challenge.campaign_id == campaign.id, Challenge.status == "ACTIVE").scalar() or 0
    verified_total = other_verified + 1
    will_complete = total > 0 and verified_total >= total and enrollment.status != "COMPLETED"
    if will_complete and not _funding_available(db, campaign, Decimal(campaign.gross_reward_per_user)):
        raise HTTPException(409, "Reward inventory was exhausted before this Bag could settle")
    now = datetime.now(UTC)
    completion.status = status
    completion.evidence = evidence or completion.evidence
    completion.verified_at = now
    completion.completed_at = now
    enrollment.completed_count = verified_total
    user.xp += challenge.xp_reward
    user.bag_score = min(1000, user.bag_score + max(1, challenge.xp_reward // 10))
    if will_complete:
        _settle_campaign(db, user, campaign, enrollment)
    return will_complete


def _public_config(challenge: Challenge) -> dict:
    config = dict(challenge.config or {})
    config.pop("answer", None)
    return config


def _gas_summary(db: Session, challenge: Challenge) -> dict | None:
    if challenge.category != "ONCHAIN":
        return None
    policy = db.query(GasSponsorshipPolicy).filter(GasSponsorshipPolicy.challenge_id == challenge.id).first()
    if not policy:
        return {"enabled": False, "status": "USER_PAID"}
    now = datetime.now(UTC)
    starts = _as_utc(policy.starts_at)
    ends = _as_utc(policy.ends_at)
    active = policy.status == "ACTIVE" and policy.funding_status == "VERIFIED" and (not starts or starts <= now) and (not ends or ends >= now) and Decimal(policy.spent_amount) < Decimal(policy.funded_amount)
    return {
        "enabled": True,
        "active": active,
        "status": policy.status,
        "chain": policy.chain,
        "native_asset": policy.native_asset,
        "max_native_per_claim": str(policy.max_native_per_claim),
        "max_unique_users": policy.max_unique_users,
        "max_claims": policy.max_claims,
        "max_claims_per_wallet": policy.max_claims_per_wallet,
        "starts_at": starts.isoformat() if starts else None,
        "ends_at": ends.isoformat() if ends else None,
    }


def _serialize_feed_row(db: Session, challenge: Challenge, campaign: Campaign, project: Project, completion: ChallengeCompletion | None, user: User) -> dict:
    user_reward = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.user_share_pct) / Decimal("100")
    social_auto = challenge.category == "SOCIAL" and challenge.provider == "X" and challenge.verification_type == "AUTO"
    return {
        "id": challenge.id,
        "campaign_id": campaign.id,
        "campaign_title": campaign.title,
        "project_id": project.id,
        "project_name": project.name,
        "project_symbol": project.symbol,
        "title": challenge.title,
        "description": challenge.description,
        "category": challenge.category,
        "provider": challenge.provider,
        "action": challenge.action,
        "verification_type": challenge.verification_type,
        "target_url": challenge.target_url,
        "target_id": challenge.target_id,
        "config": _public_config(challenge),
        "proof_code": make_x_proof_code(user.id, challenge.id) if social_auto else None,
        "xp_reward": challenge.xp_reward,
        "reward_asset": campaign.reward_asset,
        "user_reward": str(user_reward),
        "starts_at": campaign.starts_at.isoformat() if campaign.starts_at else None,
        "ends_at": campaign.ends_at.isoformat() if campaign.ends_at else None,
        "completion_status": completion.status if completion else None,
        "gas_pass": _gas_summary(db, challenge),
    }


def _verify_onchain_transaction(db: Session, user: User, project: Project, challenge: Challenge, tx_hash: str) -> dict:
    tx_hash = tx_hash.strip()
    if not _valid_tx_hash(tx_hash):
        raise HTTPException(400, "Paste a valid EVM transaction hash beginning 0x followed by 64 hexadecimal characters")
    wallet = db.query(WalletConnection).filter(WalletConnection.user_id == user.id, WalletConnection.verified_at.isnot(None)).order_by(WalletConnection.is_primary.desc(), WalletConnection.verified_at.desc()).first()
    if not wallet:
        raise HTTPException(409, "Connect and verify an EVM wallet before verifying on-chain Bag Work")
    existing = db.query(ChallengeOnchainProof).filter(ChallengeOnchainProof.challenge_id == challenge.id, ChallengeOnchainProof.tx_hash == tx_hash).first()
    if existing:
        if existing.user_id == user.id:
            return {"verification": "ONCHAIN_RPC", "tx_hash": tx_hash, "chain": existing.chain, "from": existing.wallet_address, "to": existing.target_address, "reused": False}
        raise HTTPException(409, "This transaction has already been used to verify this Bag Work activity")

    config = dict(challenge.config or {})
    chain = str(config.get("chain") or project.chain or "").strip()
    if chain.lower() not in SUPPORTED_EVM_CHAINS:
        raise HTTPException(409, "Automatic on-chain verification currently supports Avalanche, Ethereum, Base, Arbitrum and Polygon")
    target = str(config.get("target_address") or challenge.target_id or "").strip()
    if not target or not target.startswith("0x") or len(target) != 42:
        raise HTTPException(409, "This on-chain Bag Work activity does not have a valid configured target address")

    receipt = rpc_call(chain, "eth_getTransactionReceipt", [tx_hash])
    tx = rpc_call(chain, "eth_getTransactionByHash", [tx_hash])
    if not receipt or not tx:
        raise HTTPException(400, "Transaction was not found on the configured chain")
    try:
        succeeded = int(str(receipt.get("status") or "0x0"), 16) == 1
    except (TypeError, ValueError):
        succeeded = False
    if not succeeded:
        raise HTTPException(400, "Transaction did not succeed")
    sender = str(tx.get("from") or "")
    if sender.lower() != wallet.address.lower():
        raise HTTPException(400, "Transaction was not sent from your verified NuBagz wallet")
    actual_target = str(tx.get("to") or "")
    if actual_target.lower() != target.lower():
        raise HTTPException(400, "Transaction did not interact with the required target address")

    expected_data = str(config.get("calldata") or "0x").strip().lower()
    actual_data = str(tx.get("input") or tx.get("data") or "0x").strip().lower()
    if expected_data not in {"", "0x"} and actual_data != expected_data:
        raise HTTPException(400, "Transaction calldata did not match this Bag Work activity")

    raw_expected_value = config.get("value_wei", "0")
    try:
        expected_value = int(str(raw_expected_value), 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, "This Bag Work activity has invalid configured transaction value") from exc
    raw_actual_value = tx.get("value") or "0x0"
    try:
        actual_value = int(str(raw_actual_value), 16) if str(raw_actual_value).lower().startswith("0x") else int(str(raw_actual_value))
    except (TypeError, ValueError):
        raise HTTPException(400, "Transaction value could not be verified")
    if actual_value != expected_value:
        raise HTTPException(400, "Transaction value did not match this Bag Work activity")

    proof = ChallengeOnchainProof(challenge_id=challenge.id, user_id=user.id, wallet_address=wallet.address, chain=chain, tx_hash=tx_hash, target_address=actual_target or target)
    db.add(proof)
    db.flush()
    return {"verification": "ONCHAIN_RPC", "tx_hash": tx_hash, "chain": chain, "from": sender, "to": actual_target, "reused": False}


@router.get("")
def list_bag_work(category: str | None = Query(default=None), provider: str | None = Query(default=None), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    now = datetime.now(UTC)
    q = db.query(Challenge, Campaign, Project).join(Campaign, Campaign.id == Challenge.campaign_id).join(Project, Project.id == Campaign.project_id).filter(Challenge.status == "ACTIVE", Campaign.status == "LIVE", Project.status.in_(PUBLIC_PROJECT_STATUSES))
    if category:
        q = q.filter(Challenge.category == category.upper())
    if provider:
        q = q.filter(Challenge.provider == provider.upper())
    rows = []
    for challenge, campaign, project in q.order_by(Campaign.featured.desc(), Campaign.created_at.desc(), Challenge.position).all():
        starts = _as_utc(campaign.starts_at)
        ends = _as_utc(campaign.ends_at)
        if starts and starts > now:
            continue
        if ends and ends < now:
            continue
        completion = db.query(ChallengeCompletion).filter(ChallengeCompletion.user_id == user.id, ChallengeCompletion.challenge_id == challenge.id).first()
        rows.append(_serialize_feed_row(db, challenge, campaign, project, completion, user))
    return rows


@router.post("/{challenge_id}/complete")
def complete_challenge(challenge_id: int, data: ChallengeCompleteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    challenge = db.get(Challenge, challenge_id)
    if not challenge or challenge.status != "ACTIVE":
        raise HTTPException(404, "Bag Work activity not found")
    campaign = db.get(Campaign, challenge.campaign_id)
    project = db.get(Project, campaign.project_id) if campaign else None
    if not campaign or campaign.status != "LIVE" or not project or project.status not in PUBLIC_PROJECT_STATUSES:
        raise HTTPException(404, "This Bag is not live")
    if db.query(ChallengeCompletion).filter(ChallengeCompletion.user_id == user.id, ChallengeCompletion.challenge_id == challenge.id).first():
        raise HTTPException(409, "This Bag Work activity has already been submitted")
    trust = evaluate_user(db, user)
    if trust.trust_level == "RESTRICTED":
        raise HTTPException(403, "This account is restricted from completing reward opportunities pending trust review")
    completion = ChallengeCompletion(user_id=user.id, challenge_id=challenge.id, status="PENDING", answer=data.answer, evidence={"submission": data.evidence} if data.evidence else None)
    db.add(completion)
    db.flush()
    verification = challenge.verification_type.upper()
    if verification == "PROJECT_REVIEW":
        if not data.evidence or not data.evidence.strip():
            raise HTTPException(400, "Add a proof link or short evidence note for project review")
        _ensure_enrollment(db, user, campaign)
        db.commit()
        return {"ok": True, "status": "PENDING", "completed": False}

    evidence: dict = {"verification": verification}
    if verification == "QUIZ":
        expected = str((challenge.config or {}).get("answer") or "").strip().lower()
        actual = str(data.answer or "").strip().lower()
        if not expected or actual != expected:
            raise HTTPException(400, "That answer is not correct")
        evidence["verification"] = "QUIZ"
    elif verification == "AUTO":
        if challenge.category == "SOCIAL" and challenge.provider == "X":
            if not data.evidence or not data.evidence.strip():
                raise HTTPException(400, "Paste the URL of your public X proof post")
            account = db.query(SocialAccount).filter(SocialAccount.user_id == user.id, SocialAccount.provider == "X").first()
            if not account:
                raise HTTPException(409, "Connect your X account in My Bag before verifying this activity")
            proof_code = make_x_proof_code(user.id, challenge.id)
            try:
                verified, evidence = verify_x_post_proof(account, challenge, data.evidence.strip(), proof_code)
            except XVerificationUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            if not verified:
                reason = str(evidence.get("reason") or "")
                messages = {"wrong_author":"That post was not published by the X account connected to your NuBagz profile.","url_author_mismatch":"That X post URL does not match your connected X username.","proof_code_missing":"Your unique NuBagz proof code is missing from that X post.","multiple_proof_codes":"Use one NuBagz proof code per X post.","challenge_requirement_missing":"That X post is missing the required phrase, mention, hashtag or link.","post_not_public_or_not_found":"NuBagz could not find that as a public X post.","post_text_unavailable":"X did not expose readable public text for that post."}
                raise HTTPException(400, messages.get(reason, "NuBagz could not verify that public X proof post."))
        elif challenge.category == "ONCHAIN":
            if not data.evidence or not data.evidence.strip():
                raise HTTPException(400, "Paste the transaction hash for this on-chain activity")
            evidence = _verify_onchain_transaction(db, user, project, challenge, data.evidence.strip())
        else:
            raise HTTPException(400, "Automatic verification is not configured for this Bag Work activity")
    elif verification != "SELF_ATTEST":
        raise HTTPException(400, f"Unsupported verification type {verification}")

    completed_now = _finalize_completion(db, user, campaign, challenge, completion, "VERIFIED", evidence)
    db.commit()
    return {"ok": True, "status": "VERIFIED", "completed": completed_now, "xp": user.xp, "bag_score": user.bag_score}


@router.post("/completions/{completion_id}/decision")
def decide_completion(completion_id: int, data: ChallengeDecisionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    completion = db.get(ChallengeCompletion, completion_id)
    if not completion:
        raise HTTPException(404, "Submission not found")
    if completion.status != "PENDING":
        raise HTTPException(409, "This submission has already been reviewed")
    challenge = db.get(Challenge, completion.challenge_id)
    campaign = db.get(Campaign, challenge.campaign_id) if challenge else None
    project = db.get(Project, campaign.project_id) if campaign else None
    if not challenge or not campaign or not project or project.owner_id != user.id:
        raise HTTPException(404, "Submission not found")
    decision = data.status.upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise HTTPException(400, "Decision must be APPROVED or REJECTED")
    if decision == "REJECTED":
        completion.status = "REJECTED"
        completion.verified_at = datetime.now(UTC)
        db.commit()
        return {"ok": True, "status": "REJECTED", "completed": False}
    worker = db.get(User, completion.user_id)
    if not worker:
        raise HTTPException(404, "Worker account not found")
    completed_now = _finalize_completion(db, worker, campaign, challenge, completion, "APPROVED", completion.evidence)
    db.commit()
    return {"ok": True, "status": "APPROVED", "completed": completed_now}


@router.get("/submissions/project")
def project_submissions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(ChallengeCompletion, Challenge, Campaign, Project, User).join(Challenge, Challenge.id == ChallengeCompletion.challenge_id).join(Campaign, Campaign.id == Challenge.campaign_id).join(Project, Project.id == Campaign.project_id).join(User, User.id == ChallengeCompletion.user_id).filter(Project.owner_id == user.id, ChallengeCompletion.status == "PENDING", Challenge.verification_type == "PROJECT_REVIEW").order_by(ChallengeCompletion.submitted_at.asc()).all()
    return [{"id":completion.id,"challenge_id":challenge.id,"challenge_title":challenge.title,"campaign_title":campaign.title,"project_name":project.name,"username":worker.username,"evidence":completion.evidence,"submitted_at":completion.submitted_at.isoformat()} for completion,challenge,campaign,project,worker in rows]
