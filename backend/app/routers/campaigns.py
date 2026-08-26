from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..challenge_models import Challenge, ChallengeCompletion
from ..db import get_db
from ..deps import get_current_user
from ..economy import campaign_distributed_total
from ..economy_models import CampaignAccessRule, CampaignFunding
from ..integration_models import GasSponsorshipPolicy
from ..models import Campaign, Enrollment, Project, User
from ..schemas import CampaignCreate, CampaignOut, ChallengeOut
from .risk import evaluate_user

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])
PUBLIC_PROJECT_STATUSES = {"LIVE", "APPROVED"}
GAS_NATIVE = {
    "robinhood": "ETH",
    "avalanche": "AVAX",
    "ethereum": "ETH",
    "base": "ETH",
    "arbitrum": "ETH",
    "polygon": "POL",
}


def _public_project(db: Session, campaign: Campaign):
    project = db.get(Project, campaign.project_id)
    return project if project and project.status in PUBLIC_PROJECT_STATUSES else None


def serialize_campaign(campaign: Campaign, db: Session) -> CampaignOut:
    enrolled = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == campaign.id).scalar() or 0
    completed = db.query(func.count(Enrollment.id)).filter(
        Enrollment.campaign_id == campaign.id,
        Enrollment.status == "COMPLETED",
    ).scalar() or 0
    payload = CampaignOut.model_validate(campaign)
    payload.enrolled_count = enrolled
    payload.completed_count = completed
    payload.challenges = []
    for row in db.query(Challenge).filter(
        Challenge.campaign_id == campaign.id
    ).order_by(Challenge.position).all():
        public = {
            "id": row.id,
            "campaign_id": row.campaign_id,
            "title": row.title,
            "description": row.description,
            "category": row.category,
            "provider": row.provider,
            "action": row.action,
            "verification_type": row.verification_type,
            "target_url": row.target_url,
            "target_id": row.target_id,
            "config": {key: value for key, value in (row.config or {}).items() if key != "answer"},
            "xp_reward": row.xp_reward,
            "position": row.position,
            "status": row.status,
            "created_at": row.created_at,
        }
        payload.challenges.append(ChallengeOut.model_validate(public))
    return payload


def funding_available(db: Session, campaign: Campaign, next_gross: Decimal = Decimal("0")) -> bool:
    funding = db.query(CampaignFunding).filter(
        CampaignFunding.campaign_id == campaign.id,
        CampaignFunding.status == "VERIFIED",
    ).first()
    if not funding:
        return False
    return Decimal(funding.verified_amount) - campaign_distributed_total(db, campaign.id) >= next_gross


def fully_funded(db: Session, campaign: Campaign) -> bool:
    funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign.id).first()
    required = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.max_users)
    return bool(
        funding
        and funding.status == "VERIFIED"
        and Decimal(funding.verified_amount) >= required
    )


@router.get("", response_model=list[CampaignOut])
def list_campaigns(
    category: str | None = Query(default=None),
    featured: bool | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(Campaign).join(Project).options(
        joinedload(Campaign.project), joinedload(Campaign.missions)
    ).filter(
        Campaign.status == "LIVE",
        Project.status.in_(PUBLIC_PROJECT_STATUSES),
    )
    if category:
        q = q.filter(Campaign.category == category.upper())
    if featured is not None:
        q = q.filter(Campaign.featured == featured)
    return [serialize_campaign(campaign, db) for campaign in q.order_by(
        Campaign.featured.desc(), Campaign.created_at.desc()
    ).all()]


@router.get("/mine", response_model=list[CampaignOut])
def my_campaigns(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = db.query(Campaign).join(Project).options(
        joinedload(Campaign.project), joinedload(Campaign.missions)
    ).filter(Project.owner_id == user.id).order_by(Campaign.created_at.desc()).all()
    return [serialize_campaign(campaign, db) for campaign in rows]


@router.post("", response_model=CampaignOut)
def create_campaign(
    data: CampaignCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = db.get(Project, data.project_id)
    if not project or project.owner_id != user.id:
        raise HTTPException(404, "Project not found")
    if project.status not in PUBLIC_PROJECT_STATUSES:
        raise HTTPException(400, "Suspended or archived projects cannot create new Bags")

    campaign = Campaign(
        **data.model_dump(exclude={"missions", "challenges"}),
        status="DRAFT",
    )
    db.add(campaign)
    db.flush()
    for index, challenge_data in enumerate(data.challenges):
        challenge = Challenge(
            campaign_id=campaign.id,
            position=index,
            **challenge_data.model_dump(exclude={"gas_sponsorship"}),
        )
        db.add(challenge)
        db.flush()
        gas = challenge_data.gas_sponsorship
        if gas and gas.enabled:
            chain = gas.chain.strip().lower()
            if chain == "robinhood chain":
                chain = "robinhood"
            if chain not in GAS_NATIVE:
                raise HTTPException(400, "Gas Pass currently supports Robinhood, Avalanche, Ethereum, Base, Arbitrum and Polygon")
            stored_chain = "Robinhood" if chain == "robinhood" else gas.chain.strip().title()
            db.add(GasSponsorshipPolicy(
                challenge_id=challenge.id,
                project_id=project.id,
                created_by_id=user.id,
                chain=stored_chain,
                native_asset=GAS_NATIVE[chain],
                max_native_per_claim=gas.max_native_per_claim,
                max_unique_users=gas.max_unique_users,
                max_claims=gas.max_claims,
                max_claims_per_wallet=gas.max_claims_per_wallet,
                funded_amount=gas.funded_amount,
                funding_reference=gas.funding_reference.strip(),
                starts_at=gas.starts_at,
                ends_at=gas.ends_at,
                funding_status="DECLARED",
                status="FUNDING_PENDING",
            ))
    db.commit()
    campaign = db.query(Campaign).options(
        joinedload(Campaign.project), joinedload(Campaign.missions)
    ).filter(Campaign.id == campaign.id).first()
    return serialize_campaign(campaign, db)


@router.post("/{campaign_id}/publish")
def publish_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    campaign = db.get(Campaign, campaign_id)
    project = db.get(Project, campaign.project_id) if campaign else None
    if not campaign or not project or project.owner_id != user.id:
        raise HTTPException(404, "Bag not found")
    if project.status not in PUBLIC_PROJECT_STATUSES:
        raise HTTPException(409, "This project is not currently publishable")
    if campaign.status == "SUSPENDED":
        raise HTTPException(409, "A suspended Bag must be restored by moderation before it can publish")
    if not fully_funded(db, campaign):
        required = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.max_users)
        raise HTTPException(409, f"Verify at least {required} {campaign.reward_asset} of reward funding before publishing")
    active_work = db.query(func.count(Challenge.id)).filter(
        Challenge.campaign_id == campaign.id,
        Challenge.status == "ACTIVE",
    ).scalar() or 0
    if not active_work:
        raise HTTPException(409, "Add at least one active unified Bag Work Challenge before publishing")
    campaign.status = "LIVE"
    db.commit()
    return {"ok": True, "status": campaign.status}


@router.post("/{campaign_id}/pause")
def pause_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    campaign = db.get(Campaign, campaign_id)
    project = db.get(Project, campaign.project_id) if campaign else None
    if not campaign or not project or project.owner_id != user.id:
        raise HTTPException(404, "Bag not found")
    if campaign.status == "SUSPENDED":
        raise HTTPException(409, "Moderation-suspended Bags cannot be changed by the creator")
    campaign.status = "PAUSED"
    db.commit()
    return {"ok": True, "status": campaign.status}


@router.get("/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).options(
        joinedload(Campaign.project), joinedload(Campaign.missions)
    ).filter(Campaign.id == campaign_id).first()
    if not campaign or not _public_project(db, campaign):
        raise HTTPException(404, "Bag not found")
    return serialize_campaign(campaign, db)


@router.post("/{campaign_id}/enroll")
def enroll(
    campaign_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign or campaign.status != "LIVE" or not _public_project(db, campaign):
        raise HTTPException(404, "Bag is not live")
    existing = db.query(Enrollment).filter(
        Enrollment.user_id == user.id,
        Enrollment.campaign_id == campaign_id,
    ).first()
    if existing:
        return {"ok": True, "enrollment_id": existing.id, "status": existing.status}
    if not funding_available(db, campaign, Decimal(campaign.gross_reward_per_user)):
        raise HTTPException(409, "This Bag is temporarily unavailable because verified reward inventory is exhausted")
    trust = evaluate_user(db, user)
    if trust.trust_level == "RESTRICTED":
        raise HTTPException(403, "This account is restricted from new reward opportunities pending trust review")
    access_rule = db.query(CampaignAccessRule).filter(
        CampaignAccessRule.campaign_id == campaign_id
    ).first()
    if access_rule and user.bag_score < access_rule.min_bag_score:
        raise HTTPException(403, f"BagScore {access_rule.min_bag_score}+ required for this opportunity")
    enrolled_count = db.query(func.count(Enrollment.id)).filter(
        Enrollment.campaign_id == campaign_id
    ).scalar() or 0
    if enrolled_count >= campaign.max_users:
        raise HTTPException(409, "This Bag is full")
    enrollment = Enrollment(user_id=user.id, campaign_id=campaign_id)
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return {"ok": True, "enrollment_id": enrollment.id, "status": enrollment.status}


@router.post("/{campaign_id}/missions/{mission_id}/complete")
def retired_mission_completion(campaign_id: int, mission_id: int):
    raise HTTPException(
        410,
        "Legacy Mission completion is retired. This Bag must use the unified Bag Work Challenge flow.",
    )


@router.get("/{campaign_id}/progress")
def progress(
    campaign_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign or not _public_project(db, campaign):
        raise HTTPException(404, "Bag not found")
    enrollment = db.query(Enrollment).filter(
        Enrollment.user_id == user.id,
        Enrollment.campaign_id == campaign_id,
    ).first()
    completions = db.query(ChallengeCompletion, Challenge).join(
        Challenge, Challenge.id == ChallengeCompletion.challenge_id
    ).filter(
        ChallengeCompletion.user_id == user.id,
        Challenge.campaign_id == campaign_id,
    ).all()
    verified = [
        challenge.id
        for completion, challenge in completions
        if completion.status in {"VERIFIED", "APPROVED"}
    ]
    pending = [
        challenge.id
        for completion, challenge in completions
        if completion.status == "PENDING"
    ]
    return {
        "joined": bool(enrollment),
        "status": enrollment.status if enrollment else None,
        "completed_challenge_ids": verified,
        "pending_challenge_ids": pending,
        "earned_amount": str(enrollment.earned_amount) if enrollment else "0",
    }
