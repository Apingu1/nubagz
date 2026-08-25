from datetime import datetime, UTC
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import Campaign, Mission, Project, User
from ..challenge_models import Challenge
from ..economy_models import CampaignFunding

router = APIRouter(prefix="/api/funding", tags=["funding"])
PUBLIC_PROJECT_STATUSES = {"LIVE", "APPROVED"}


class FundingDeclareIn(BaseModel):
    amount: Decimal = Field(gt=0)
    tx_hash: str | None = Field(default=None, max_length=255)


class FundingVerifyIn(BaseModel):
    amount: Decimal = Field(gt=0)
    tx_hash: str | None = Field(default=None, max_length=255)


def required_amount(campaign: Campaign) -> Decimal:
    return Decimal(campaign.gross_reward_per_user) * Decimal(campaign.max_users)


def owner_or_admin(campaign: Campaign, db: Session, user: User):
    project = db.get(Project, campaign.project_id)
    if not project or (project.owner_id != user.id and user.role != "ADMIN"):
        raise HTTPException(403, "You do not manage this campaign")
    return project


def _has_work(db: Session, campaign_id: int) -> bool:
    active_challenges = db.query(func.count(Challenge.id)).filter(
        Challenge.campaign_id == campaign_id,
        Challenge.status == "ACTIVE",
    ).scalar() or 0
    if active_challenges:
        return True
    legacy_missions = db.query(func.count(Mission.id)).filter(Mission.campaign_id == campaign_id).scalar() or 0
    return bool(legacy_missions)


def _auto_publish_if_ready(db: Session, campaign: Campaign) -> bool:
    """Make a newly funded Bag discoverable without a hidden second publish gate.

    DRAFT/PENDING means the Bag is waiting for objective reward funding. Once an
    administrator verifies enough inventory, it becomes LIVE automatically if its
    project is public and it has work configured. PAUSED and SUSPENDED are left
    untouched because those are intentional creator/moderation states.
    """
    if campaign.status not in {"DRAFT", "PENDING"}:
        return False
    project = db.get(Project, campaign.project_id)
    if not project or project.status not in PUBLIC_PROJECT_STATUSES or not _has_work(db, campaign.id):
        return False
    campaign.status = "LIVE"
    return True


def payload(campaign: Campaign, funding: CampaignFunding | None):
    required = required_amount(campaign)
    fully_funded = bool(funding and funding.status == "VERIFIED" and Decimal(funding.verified_amount) >= required)
    return {
        "campaign_id": campaign.id,
        "asset": campaign.reward_asset,
        "required_amount": str(required),
        "declared_amount": str(funding.declared_amount if funding else Decimal("0")),
        "verified_amount": str(funding.verified_amount if funding else Decimal("0")),
        "status": funding.status if funding else "UNFUNDED",
        "tx_hash": funding.tx_hash if funding else None,
        "fully_funded": fully_funded,
        "campaign_status": campaign.status,
        "discoverable": bool(fully_funded and campaign.status == "LIVE"),
    }


@router.get("/campaigns/{campaign_id}")
def campaign_funding(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    owner_or_admin(campaign, db, user)
    funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign_id).first()
    return payload(campaign, funding)


@router.get("/mine")
def my_campaign_funding(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaigns = db.query(Campaign).join(Project, Project.id == Campaign.project_id).filter(Project.owner_id == user.id).all()
    funding_by_campaign = {row.campaign_id: row for row in db.query(CampaignFunding).filter(CampaignFunding.campaign_id.in_([c.id for c in campaigns] or [-1])).all()}
    return [payload(c, funding_by_campaign.get(c.id)) for c in campaigns]


@router.post("/campaigns/{campaign_id}/declare")
def declare_funding(campaign_id: int, data: FundingDeclareIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    owner_or_admin(campaign, db, user)
    funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign_id).first()
    if not funding:
        funding = CampaignFunding(campaign_id=campaign_id)
        db.add(funding)
    funding.declared_amount = data.amount
    funding.verified_amount = Decimal("0")
    funding.tx_hash = data.tx_hash
    funding.status = "DECLARED"
    funding.verified_by_id = None
    funding.verified_at = None
    db.commit()
    db.refresh(funding)
    return payload(campaign, funding)


@router.post("/campaigns/{campaign_id}/verify")
def verify_funding(campaign_id: int, data: FundingVerifyIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    required = required_amount(campaign)
    if data.amount < required:
        raise HTTPException(400, f"Verified funding must cover the maximum reward obligation of {required} {campaign.reward_asset}")
    funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign_id).first()
    if not funding:
        funding = CampaignFunding(campaign_id=campaign_id, declared_amount=data.amount)
        db.add(funding)
    funding.verified_amount = data.amount
    funding.declared_amount = max(Decimal(funding.declared_amount or 0), data.amount)
    funding.tx_hash = data.tx_hash or funding.tx_hash
    funding.status = "VERIFIED"
    funding.verified_by_id = admin.id
    funding.verified_at = datetime.now(UTC)
    _auto_publish_if_ready(db, campaign)
    db.commit()
    db.refresh(funding)
    db.refresh(campaign)
    return payload(campaign, funding)
