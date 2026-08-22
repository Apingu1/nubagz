from datetime import datetime, UTC
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import Campaign, Enrollment, LedgerEntry, Project, User
from ..challenge_models import Challenge, ChallengeCompletion, SocialAccount
from ..economy_models import CampaignAccessRule, CampaignFunding
from ..marketplace_models import BagBuilderAttribution, BagBuilderPathway
from ..engagement_models import ReferralConversion
from ..economy import campaign_distributed_total
from ..schemas import ChallengeCompleteIn, ChallengeDecisionIn
from ..x_verifier import XVerificationUnavailable, make_x_proof_code, verify_x_post_proof
from .risk import evaluate_user


router = APIRouter(prefix="/api/challenges", tags=["bag-work"])
REFERRAL_ELIGIBLE_LEVELS = {"NORMAL", "VERIFIED"}
VERIFIED_STATUSES = {"VERIFIED", "APPROVED"}


def _funding_available(db: Session, campaign: Campaign, next_gross: Decimal = Decimal("0")) -> bool:
    funding = db.query(CampaignFunding).filter(
        CampaignFunding.campaign_id == campaign.id,
        CampaignFunding.status == "VERIFIED",
    ).first()
    if not funding:
        return False
    distributed = campaign_distributed_total(db, campaign.id)
    return Decimal(funding.verified_amount) - distributed >= next_gross


def _ensure_enrollment(db: Session, user: User, campaign: Campaign) -> Enrollment:
    enrollment = db.query(Enrollment).filter(
        Enrollment.user_id == user.id,
        Enrollment.campaign_id == campaign.id,
    ).first()
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

    builder_pathway = None
    builder_profile = None
    builder_user = None
    attribution = db.query(BagBuilderAttribution).filter(
        BagBuilderAttribution.user_id == user.id,
        BagBuilderAttribution.campaign_id == campaign.id,
    ).first()
    if attribution:
        pathway = db.get(BagBuilderPathway, attribution.pathway_id)
        if pathway and pathway.status == "APPROVED" and pathway.campaign_id == campaign.id:
            candidate = db.get(User, pathway.creator_id)
            project = db.get(Project, campaign.project_id)
            if candidate and project and candidate.id != project.owner_id:
                builder_pathway = pathway
                builder_user = candidate
                builder_profile = evaluate_user(db, candidate)

    user_amount = gross * Decimal(campaign.user_share_pct) / Decimal("100")
    platform_amount = gross * Decimal(campaign.nubagz_share_pct) / Decimal("100")
    referral_amount = gross * Decimal(campaign.referral_share_pct) / Decimal("100")
    builder_amount = Decimal("0")
    builder_id = None
    if builder_pathway and builder_user and builder_profile and builder_profile.trust_level != "RESTRICTED":
        builder_amount = gross * Decimal(builder_pathway.creator_share_pct) / Decimal("100")
        builder_amount = min(builder_amount, platform_amount)
        builder_id = builder_user.id
        platform_amount -= builder_amount

    enrollment.status = "COMPLETED"
    enrollment.completed_at = datetime.now(UTC)
    enrollment.earned_amount = user_amount
    db.add(LedgerEntry(user_id=user.id,campaign_id=campaign.id,asset_symbol=campaign.reward_asset,amount=user_amount,entry_type="CAMPAIGN_REWARD",note=f"Completed {campaign.title}"))
    if builder_id and builder_amount > 0:
        db.add(LedgerEntry(user_id=builder_id,campaign_id=campaign.id,asset_symbol=campaign.reward_asset,amount=builder_amount,entry_type="BUILDER_SHARE",note=f"BagBuilder share from {campaign.title}"))
    db.add(LedgerEntry(user_id=None,campaign_id=campaign.id,asset_symbol=campaign.reward_asset,amount=platform_amount,entry_type="PLATFORM_SHARE",note="NuBagz campaign share"))
    if user.referred_by_id and referral_amount > 0:
        referrer_level = referrer_profile.trust_level if referrer_profile else "REVIEW"
        if referrer_level not in REFERRAL_ELIGIBLE_LEVELS:
            db.add(LedgerEntry(user_id=None,campaign_id=campaign.id,asset_symbol=campaign.reward_asset,amount=referral_amount,entry_type="COMMUNITY_SHARE",note=f"Referral share redirected because referrer trust is {referrer_level}"))
            db.add(ReferralConversion(referrer_id=user.referred_by_id,referred_user_id=user.id,campaign_id=campaign.id,asset_symbol=campaign.reward_asset,allocated_amount=referral_amount,paid_amount=0,status="REDIRECTED",reason=f"Referrer {referrer_level.lower()} at settlement"))
        else:
            db.add(LedgerEntry(user_id=user.referred_by_id,campaign_id=campaign.id,asset_symbol=campaign.reward_asset,amount=referral_amount,entry_type="REFERRAL_SHARE",note=f"Referral reward from {user.username}"))
            db.add(ReferralConversion(referrer_id=user.referred_by_id,referred_user_id=user.id,campaign_id=campaign.id,asset_symbol=campaign.reward_asset,allocated_amount=referral_amount,paid_amount=referral_amount,status="PAID",reason="Funded campaign conversion"))
    else:
        db.add(LedgerEntry(user_id=None,campaign_id=campaign.id,asset_symbol=campaign.reward_asset,amount=referral_amount,entry_type="COMMUNITY_SHARE",note="Unassigned referral share"))
    user.bag_score = min(1000, user.bag_score + 20)


def _finalize_completion(db: Session,user: User,campaign: Campaign,challenge: Challenge,completion: ChallengeCompletion,status: str,evidence: dict | None = None) -> bool:
    enrollment = _ensure_enrollment(db, user, campaign)
    other_verified = db.query(func.count(ChallengeCompletion.id)).join(Challenge, Challenge.id == ChallengeCompletion.challenge_id).filter(ChallengeCompletion.user_id == user.id,Challenge.campaign_id == campaign.id,ChallengeCompletion.id != completion.id,ChallengeCompletion.status.in_(VERIFIED_STATUSES)).scalar() or 0
    total = db.query(func.count(Challenge.id)).filter(Challenge.campaign_id == campaign.id,Challenge.status == "ACTIVE").scalar() or 0
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


def _serialize_feed_row(challenge: Challenge,campaign: Campaign,project: Project,completion: ChallengeCompletion | None,user: User) -> dict:
    user_reward = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.user_share_pct) / Decimal("100")
    social_auto = challenge.category == "SOCIAL" and challenge.provider == "X" and challenge.verification_type == "AUTO"
    return {"id":challenge.id,"campaign_id":campaign.id,"campaign_title":campaign.title,"project_id":project.id,"project_name":project.name,"project_symbol":project.symbol,"title":challenge.title,"description":challenge.description,"category":challenge.category,"provider":challenge.provider,"action":challenge.action,"verification_type":challenge.verification_type,"target_url":challenge.target_url,"target_id":challenge.target_id,"config":_public_config(challenge),"proof_code":make_x_proof_code(user.id, challenge.id) if social_auto else None,"xp_reward":challenge.xp_reward,"reward_asset":campaign.reward_asset,"user_reward":str(user_reward),"starts_at":campaign.starts_at.isoformat() if campaign.starts_at else None,"ends_at":campaign.ends_at.isoformat() if campaign.ends_at else None,"completion_status":completion.status if completion else None}


@router.get("")
def list_bag_work(category: str | None = Query(default=None),provider: str | None = Query(default=None),db: Session = Depends(get_db),user: User = Depends(get_current_user)):
    now = datetime.now(UTC)
    q = db.query(Challenge, Campaign, Project).join(Campaign, Campaign.id == Challenge.campaign_id).join(Project, Project.id == Campaign.project_id).filter(Challenge.status == "ACTIVE",Campaign.status == "LIVE")
    if category: q = q.filter(Challenge.category == category.upper())
    if provider: q = q.filter(Challenge.provider == provider.upper())
    rows = []
    for challenge, campaign, project in q.order_by(Campaign.featured.desc(), Campaign.created_at.desc(), Challenge.position).all():
        if campaign.starts_at and campaign.starts_at > now: continue
        if campaign.ends_at and campaign.ends_at < now: continue
        completion = db.query(ChallengeCompletion).filter(ChallengeCompletion.user_id == user.id,ChallengeCompletion.challenge_id == challenge.id).first()
        rows.append(_serialize_feed_row(challenge, campaign, project, completion, user))
    return rows


@router.post("/{challenge_id}/complete")
def complete_challenge(challenge_id: int,data: ChallengeCompleteIn,db: Session = Depends(get_db),user: User = Depends(get_current_user)):
    challenge = db.get(Challenge, challenge_id)
    if not challenge or challenge.status != "ACTIVE": raise HTTPException(404, "Bag Work activity not found")
    campaign = db.get(Campaign, challenge.campaign_id)
    if not campaign or campaign.status != "LIVE": raise HTTPException(404, "This Bag is not live")
    if db.query(ChallengeCompletion).filter(ChallengeCompletion.user_id == user.id,ChallengeCompletion.challenge_id == challenge.id).first(): raise HTTPException(409, "This Bag Work activity has already been submitted")
    trust = evaluate_user(db, user)
    if trust.trust_level == "RESTRICTED": raise HTTPException(403, "This account is restricted from completing reward opportunities pending trust review")
    completion = ChallengeCompletion(user_id=user.id,challenge_id=challenge.id,status="PENDING",answer=data.answer,evidence={"submission": data.evidence} if data.evidence else None)
    db.add(completion);db.flush()
    verification = challenge.verification_type.upper()
    if verification == "PROJECT_REVIEW":
        if not data.evidence or not data.evidence.strip(): raise HTTPException(400, "Add a proof link or short evidence note for project review")
        _ensure_enrollment(db, user, campaign);db.commit();return {"ok": True, "status": "PENDING", "completed": False}
    evidence: dict = {"verification": verification}
    if verification == "QUIZ":
        expected = str((challenge.config or {}).get("answer") or "").strip().lower();actual = str(data.answer or "").strip().lower()
        if not expected or actual != expected: raise HTTPException(400, "That answer is not correct")
        evidence["verification"] = "QUIZ"
    elif verification == "AUTO":
        if challenge.category != "SOCIAL" or challenge.provider != "X": raise HTTPException(400, "Automatic verification is not configured for this Bag Work activity")
        if not data.evidence or not data.evidence.strip(): raise HTTPException(400, "Paste the URL of your public X proof post")
        account = db.query(SocialAccount).filter(SocialAccount.user_id == user.id,SocialAccount.provider == "X").first()
        if not account: raise HTTPException(409, "Connect your X account in My Bag before verifying this activity")
        proof_code = make_x_proof_code(user.id, challenge.id)
        try: verified, evidence = verify_x_post_proof(account, challenge, data.evidence.strip(), proof_code)
        except XVerificationUnavailable as exc: raise HTTPException(503, str(exc)) from exc
        if not verified:
            reason = str(evidence.get("reason") or "")
            messages = {"wrong_author":"That post was not published by the X account connected to your NuBagz profile.","url_author_mismatch":"That X post URL does not match your connected X username.","proof_code_missing":"Your unique NuBagz proof code is missing from that X post.","multiple_proof_codes":"Use one NuBagz proof code per X post.","challenge_requirement_missing":"That X post is missing the required phrase, mention, hashtag or link.","post_not_public_or_not_found":"NuBagz could not find that as a public X post.","post_text_unavailable":"X did not expose readable public text for that post."}
            raise HTTPException(400, messages.get(reason, "NuBagz could not verify that public X proof post."))
    elif verification != "SELF_ATTEST": raise HTTPException(400, f"Unsupported verification type {verification}")
    completed_now = _finalize_completion(db, user, campaign, challenge, completion, "VERIFIED", evidence);db.commit()
    return {"ok": True, "status": "VERIFIED", "completed": completed_now, "xp": user.xp, "bag_score": user.bag_score}


@router.post("/completions/{completion_id}/decision")
def decide_completion(completion_id: int,data: ChallengeDecisionIn,db: Session = Depends(get_db),user: User = Depends(get_current_user)):
    completion = db.get(ChallengeCompletion, completion_id)
    if not completion: raise HTTPException(404, "Submission not found")
    if completion.status != "PENDING": raise HTTPException(409, "This submission has already been reviewed")
    challenge = db.get(Challenge, completion.challenge_id);campaign = db.get(Campaign, challenge.campaign_id) if challenge else None;project = db.get(Project, campaign.project_id) if campaign else None
    if not challenge or not campaign or not project or project.owner_id != user.id: raise HTTPException(404, "Submission not found")
    decision = data.status.upper()
    if decision not in {"APPROVED", "REJECTED"}: raise HTTPException(400, "Decision must be APPROVED or REJECTED")
    if decision == "REJECTED": completion.status="REJECTED";completion.verified_at=datetime.now(UTC);db.commit();return {"ok":True,"status":"REJECTED","completed":False}
    worker = db.get(User, completion.user_id)
    if not worker: raise HTTPException(404, "Worker account not found")
    completed_now = _finalize_completion(db, worker, campaign, challenge, completion, "APPROVED", completion.evidence);db.commit();return {"ok":True,"status":"APPROVED","completed":completed_now}


@router.get("/submissions/project")
def project_submissions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(ChallengeCompletion, Challenge, Campaign, Project, User).join(Challenge, Challenge.id == ChallengeCompletion.challenge_id).join(Campaign, Campaign.id == Challenge.campaign_id).join(Project, Project.id == Campaign.project_id).join(User, User.id == ChallengeCompletion.user_id).filter(Project.owner_id == user.id,ChallengeCompletion.status == "PENDING").order_by(ChallengeCompletion.submitted_at.asc()).all()
    return [{"id":completion.id,"challenge_id":challenge.id,"challenge_title":challenge.title,"campaign_title":campaign.title,"project_name":project.name,"username":worker.username,"evidence":completion.evidence,"submitted_at":completion.submitted_at.isoformat()} for completion, challenge, campaign, project, worker in rows]
