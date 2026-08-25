from datetime import datetime, UTC
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..bag_lifecycle import (
    active_work_count,
    fully_funded,
    publication_blockers,
    reconcile_campaign_publication,
    reconcile_verified_drafts,
    required_amount,
)
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import Campaign, Project, User
from ..economy_models import CampaignFunding

router = APIRouter(prefix="/api/funding", tags=["funding"])


class FundingDeclareIn(BaseModel):
    amount: Decimal = Field(gt=0)
    tx_hash: str | None = Field(default=None, max_length=255)


class FundingVerifyIn(BaseModel):
    amount: Decimal = Field(gt=0)
    tx_hash: str | None = Field(default=None, max_length=255)


def owner_or_admin(campaign: Campaign, db: Session, user: User):
    project = db.get(Project, campaign.project_id)
    if not project or (project.owner_id != user.id and user.role != "ADMIN"):
        raise HTTPException(403, "You do not manage this campaign")
    return project


def payload(db: Session, campaign: Campaign, funding: CampaignFunding | None):
    required = required_amount(campaign)
    funded = fully_funded(campaign, funding)
    work_count = active_work_count(db, campaign.id)
    blockers = publication_blockers(db, campaign, funding)
    discoverable = bool(
        campaign.status == "LIVE"
        and funded
        and work_count > 0
        and not any(code.startswith("PROJECT_") for code in blockers)
    )
    return {
        "campaign_id": campaign.id,
        "asset": campaign.reward_asset,
        "required_amount": str(required),
        "declared_amount": str(funding.declared_amount if funding else Decimal("0")),
        "verified_amount": str(funding.verified_amount if funding else Decimal("0")),
        "status": funding.status if funding else "UNFUNDED",
        "tx_hash": funding.tx_hash if funding else None,
        "fully_funded": funded,
        "campaign_status": campaign.status,
        "active_work_count": work_count,
        "discoverable": discoverable,
        "discoverability_blockers": blockers,
    }


@router.get("/campaigns/{campaign_id}")
def campaign_funding(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    owner_or_admin(campaign, db, user)
    funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign_id).first()
    if reconcile_campaign_publication(db, campaign, funding):
        db.commit()
        db.refresh(campaign)
    return payload(db, campaign, funding)


@router.get("/mine")
def my_campaign_funding(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaigns = db.query(Campaign).join(Project, Project.id == Campaign.project_id).filter(Project.owner_id == user.id).all()
    campaign_ids = [c.id for c in campaigns]
    reconcile_verified_drafts(db, campaign_ids)
    funding_by_campaign = {
        row.campaign_id: row
        for row in db.query(CampaignFunding)
        .filter(CampaignFunding.campaign_id.in_(campaign_ids or [-1]))
        .all()
    }
    return [payload(db, c, funding_by_campaign.get(c.id)) for c in campaigns]


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
    return payload(db, campaign, funding)


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
    reconcile_campaign_publication(db, campaign, funding)
    db.commit()
    db.refresh(funding)
    db.refresh(campaign)
    return payload(db, campaign, funding)
