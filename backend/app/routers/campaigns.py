from datetime import datetime, UTC
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Project, Campaign, Mission, Enrollment, MissionCompletion, LedgerEntry
from ..economy_models import OnchainRule, OnchainProof, CampaignAccessRule, CampaignFunding
from ..marketplace_models import BagBuilderPathway, BagBuilderAttribution
from ..engagement_models import ReferralConversion
from ..schemas import CampaignCreate, CampaignOut, MissionCompleteIn
from ..economy import campaign_distributed_total
from .risk import evaluate_user

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])
REFERRAL_ELIGIBLE_LEVELS = {"NORMAL", "VERIFIED"}


def serialize_campaign(c: Campaign, db: Session) -> CampaignOut:
    enrolled = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == c.id).scalar() or 0
    completed = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == c.id, Enrollment.status == "COMPLETED").scalar() or 0
    payload = CampaignOut.model_validate(c); payload.enrolled_count = enrolled; payload.completed_count = completed
    return payload


def funding_available(db: Session, campaign: Campaign, next_gross: Decimal = Decimal("0")) -> bool:
    funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign.id, CampaignFunding.status == "VERIFIED").first()
    if not funding: return False
    distributed = campaign_distributed_total(db, campaign.id)
    return Decimal(funding.verified_amount) - distributed >= next_gross


@router.get("", response_model=list[CampaignOut])
def list_campaigns(category: str | None = Query(default=None), featured: bool | None = Query(default=None), db: Session = Depends(get_db)):
    q = db.query(Campaign).options(joinedload(Campaign.project), joinedload(Campaign.missions)).filter(Campaign.status == "LIVE")
    if category: q = q.filter(Campaign.category == category.upper())
    if featured is not None: q = q.filter(Campaign.featured == featured)
    return [serialize_campaign(c, db) for c in q.order_by(Campaign.featured.desc(), Campaign.created_at.desc()).all()]


@router.get("/mine", response_model=list[CampaignOut])
def my_campaigns(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Campaign).join(Project).options(joinedload(Campaign.project), joinedload(Campaign.missions)).filter(Project.owner_id == user.id).order_by(Campaign.created_at.desc()).all()
    return [serialize_campaign(c, db) for c in rows]


@router.post("", response_model=CampaignOut)
def create_campaign(data: CampaignCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = db.get(Project, data.project_id)
    if not project or project.owner_id != user.id: raise HTTPException(404, "Project not found")
    if project.status != "APPROVED": raise HTTPException(400, "Project must be approved before a campaign can be submitted")
    campaign = Campaign(**data.model_dump(exclude={"missions"}), status="PENDING"); db.add(campaign); db.flush()
    for idx, mission_data in enumerate(data.missions): db.add(Mission(campaign_id=campaign.id, position=idx, **mission_data.model_dump()))
    db.commit(); campaign = db.query(Campaign).options(joinedload(Campaign.project), joinedload(Campaign.missions)).filter(Campaign.id == campaign.id).first()
    return serialize_campaign(campaign, db)


@router.get("/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).options(joinedload(Campaign.project), joinedload(Campaign.missions)).filter(Campaign.id == campaign_id).first()
    if not campaign: raise HTTPException(404, "Bag not found")
    return serialize_campaign(campaign, db)


@router.post("/{campaign_id}/enroll")
def enroll(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign or campaign.status != "LIVE": raise HTTPException(404, "Bag is not live")
    existing = db.query(Enrollment).filter(Enrollment.user_id == user.id, Enrollment.campaign_id == campaign_id).first()
    if existing: return {"ok": True, "enrollment_id": existing.id, "status": existing.status}
    if not funding_available(db, campaign, Decimal(campaign.gross_reward_per_user)): raise HTTPException(409, "This Bag is temporarily unavailable because verified reward inventory is exhausted")
    trust = evaluate_user(db, user)
    if trust.trust_level == "RESTRICTED": raise HTTPException(403, "This account is restricted from new reward opportunities pending trust review")
    access_rule = db.query(CampaignAccessRule).filter(CampaignAccessRule.campaign_id == campaign_id).first()
    if access_rule and user.bag_score < access_rule.min_bag_score: raise HTTPException(403, f"BagScore {access_rule.min_bag_score}+ required for this opportunity")
    enrolled_count = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == campaign_id).scalar() or 0
    if enrolled_count >= campaign.max_users: raise HTTPException(409, "This Bag is full")
    enrollment = Enrollment(user_id=user.id, campaign_id=campaign_id); db.add(enrollment); db.commit(); db.refresh(enrollment)
    return {"ok": True, "enrollment_id": enrollment.id, "status": enrollment.status}


@router.post("/{campaign_id}/missions/{mission_id}/complete")
def complete_mission(campaign_id: int, mission_id: int, data: MissionCompleteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.query(Campaign).options(joinedload(Campaign.missions)).filter(Campaign.id == campaign_id, Campaign.status == "LIVE").first()
    if not campaign: raise HTTPException(404, "Bag is not live")
    mission = next((m for m in campaign.missions if m.id == mission_id), None)
    if not mission: raise HTTPException(404, "Mission not found")
    enrollment = db.query(Enrollment).filter(Enrollment.user_id == user.id, Enrollment.campaign_id == campaign_id).first()
    if not enrollment: raise HTTPException(400, "Join this Bag first")
    trust = evaluate_user(db, user)
    if trust.trust_level == "RESTRICTED": raise HTTPException(403, "This account is restricted from completing reward opportunities pending trust review")
    if db.query(MissionCompletion).filter(MissionCompletion.user_id == user.id, MissionCompletion.mission_id == mission_id).first(): raise HTTPException(409, "Mission already completed")
    onchain_rule = db.query(OnchainRule).filter(OnchainRule.mission_id == mission_id).first()
    if onchain_rule and not db.query(OnchainProof).filter(OnchainProof.rule_id == onchain_rule.id, OnchainProof.user_id == user.id).first(): raise HTTPException(400, "Complete this mission's on-chain verification before claiming completion")
    verified = True
    if mission.verification_type == "QUIZ":
        verified = bool(data.answer and mission.quiz_answer and data.answer.strip().lower() == mission.quiz_answer.strip().lower())
        if not verified: raise HTTPException(400, "That answer is not correct")
    will_complete = enrollment.completed_count + 1 >= len(campaign.missions); gross = Decimal(campaign.gross_reward_per_user)
    if will_complete and not funding_available(db, campaign, gross): raise HTTPException(409, "Reward inventory was exhausted before this Bag could settle. No final completion was recorded.")

    referrer_profile = None
    if will_complete and user.referred_by_id:
        referrer = db.get(User, user.referred_by_id)
        if referrer:
            referrer_profile = evaluate_user(db, referrer)

    builder_pathway = None
    builder_profile = None
    builder_user = None
    if will_complete:
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

    db.add(MissionCompletion(user_id=user.id, mission_id=mission_id, answer=data.answer, verified=verified)); enrollment.completed_count += 1
    user.xp += mission.xp_reward; user.bag_score = min(1000, user.bag_score + max(1, mission.xp_reward // 10)); completed_now = False
    if will_complete:
        completed_now = True; enrollment.status = "COMPLETED"; enrollment.completed_at = datetime.now(UTC)
        user_amount = gross * Decimal(campaign.user_share_pct) / Decimal("100")
        platform_amount = gross * Decimal(campaign.nubagz_share_pct) / Decimal("100")
        referral_amount = gross * Decimal(campaign.referral_share_pct) / Decimal("100")
        builder_amount = Decimal("0"); builder_id = None
        if builder_pathway and builder_user and builder_profile and builder_profile.trust_level != "RESTRICTED":
            builder_amount = gross * Decimal(builder_pathway.creator_share_pct) / Decimal("100")
            builder_amount = min(builder_amount, platform_amount)
            builder_id = builder_user.id
            platform_amount -= builder_amount
        enrollment.earned_amount = user_amount
        db.add(LedgerEntry(user_id=user.id, campaign_id=campaign.id, asset_symbol=campaign.reward_asset, amount=user_amount, entry_type="CAMPAIGN_REWARD", note=f"Completed {campaign.title}"))
        if builder_id and builder_amount > 0:
            db.add(LedgerEntry(user_id=builder_id, campaign_id=campaign.id, asset_symbol=campaign.reward_asset, amount=builder_amount, entry_type="BUILDER_SHARE", note=f"BagBuilder share from {campaign.title}"))
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
    db.commit(); return {"ok": True, "completed": completed_now, "xp": user.xp, "bag_score": user.bag_score}


@router.get("/{campaign_id}/progress")
def progress(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    enrollment = db.query(Enrollment).filter(Enrollment.user_id == user.id, Enrollment.campaign_id == campaign_id).first()
    ids = [r[0] for r in db.query(MissionCompletion.mission_id).join(Mission, Mission.id == MissionCompletion.mission_id).filter(MissionCompletion.user_id == user.id, Mission.campaign_id == campaign_id).all()]
    return {"joined": bool(enrollment), "status": enrollment.status if enrollment else None, "completed_mission_ids": ids, "earned_amount": str(enrollment.earned_amount) if enrollment else "0"}
