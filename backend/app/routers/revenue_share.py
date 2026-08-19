from datetime import datetime, UTC
from decimal import Decimal, ROUND_DOWN
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import User, Project, Campaign, Enrollment, LedgerEntry
from ..risk_models import UserTrustProfile
from ..marketplace_models import RevenueShareDistribution, RevenueShareRecipient

router = APIRouter(prefix="/api/revenue-share", tags=["revenue-share"])


class DistributionIn(BaseModel):
    campaign_id: int
    title: str = Field(min_length=4, max_length=180)
    asset_symbol: str = Field(min_length=1, max_length=24)
    funded_amount: Decimal = Field(gt=0)
    funding_reference: str = Field(min_length=4, max_length=255)


def serialize(row: RevenueShareDistribution, db: Session, user_id: int | None = None):
    project = db.get(Project, row.project_id)
    campaign = db.get(Campaign, row.campaign_id)
    recipient = db.query(RevenueShareRecipient).filter(RevenueShareRecipient.distribution_id == row.id, RevenueShareRecipient.user_id == user_id).first() if user_id else None
    return {
        "id": row.id, "project_id": row.project_id, "project_name": project.name if project else None,
        "campaign_id": row.campaign_id, "campaign_title": campaign.title if campaign else None,
        "title": row.title, "asset_symbol": row.asset_symbol, "funded_amount": str(row.funded_amount),
        "distributed_amount": str(row.distributed_amount), "funding_status": row.funding_status,
        "status": row.status, "recipient_count": row.recipient_count,
        "amount_per_recipient": str(row.amount_per_recipient) if row.amount_per_recipient is not None else None,
        "my_amount": str(recipient.amount) if recipient else None,
        "created_at": row.created_at.isoformat(), "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "disclaimer": "This is a fixed, already-funded project distribution. It is not a promised yield, APY, dividend guarantee, or investment return.",
    }


@router.get("")
def distributions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(RevenueShareDistribution).filter(RevenueShareDistribution.funding_status == "VERIFIED").order_by(RevenueShareDistribution.created_at.desc()).all()
    return [serialize(row, db, user.id) for row in rows]


@router.get("/mine")
def my_distributions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(RevenueShareDistribution).filter(RevenueShareDistribution.created_by_id == user.id).order_by(RevenueShareDistribution.created_at.desc()).all()
    return [serialize(row, db, user.id) for row in rows]


@router.get("/admin")
def admin_distributions(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rows = db.query(RevenueShareDistribution).order_by(RevenueShareDistribution.created_at.desc()).all()
    return [serialize(row, db, user.id) for row in rows]


@router.post("")
def create_distribution(data: DistributionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, data.campaign_id)
    project = db.get(Project, campaign.project_id) if campaign else None
    if not campaign or not project or project.owner_id != user.id:
        raise HTTPException(404, "Campaign not found")
    if project.status != "APPROVED":
        raise HTTPException(400, "Project must be approved before creating a revenue share distribution")
    row = RevenueShareDistribution(project_id=project.id, campaign_id=campaign.id, created_by_id=user.id, title=data.title, asset_symbol=data.asset_symbol.upper(), funded_amount=data.funded_amount, funding_reference=data.funding_reference)
    db.add(row); db.commit(); db.refresh(row)
    return serialize(row, db, user.id)


@router.post("/{distribution_id}/activate")
def activate_distribution(distribution_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    row = db.get(RevenueShareDistribution, distribution_id)
    if not row:
        raise HTTPException(404, "Distribution not found")
    if not row.funding_reference or Decimal(row.funded_amount) <= 0:
        raise HTTPException(400, "Distribution funding must be declared before activation")
    row.funding_status = "VERIFIED"; row.status = "LIVE"; db.commit()
    return serialize(row, db)


@router.post("/{distribution_id}/execute")
def execute_distribution(distribution_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(RevenueShareDistribution).filter(RevenueShareDistribution.id == distribution_id).with_for_update().first()
    project = db.get(Project, row.project_id) if row else None
    if not row or not project or project.owner_id != user.id:
        raise HTTPException(403, "Only the project owner can execute this distribution")
    if row.status != "LIVE" or row.funding_status != "VERIFIED":
        raise HTTPException(409, "Distribution is not ready to execute")
    existing = db.query(RevenueShareRecipient).filter(RevenueShareRecipient.distribution_id == row.id).first()
    if existing:
        raise HTTPException(409, "Distribution has already been executed")

    completed = db.query(Enrollment).filter(Enrollment.campaign_id == row.campaign_id, Enrollment.status == "COMPLETED").all()
    eligible_user_ids = []
    for enrollment in completed:
        participant = db.get(User, enrollment.user_id)
        trust = db.query(UserTrustProfile).filter(UserTrustProfile.user_id == enrollment.user_id).first()
        if participant and participant.is_active and not (trust and trust.trust_level == "RESTRICTED"):
            eligible_user_ids.append(enrollment.user_id)
    eligible_user_ids = sorted(set(eligible_user_ids))
    if not eligible_user_ids:
        raise HTTPException(409, "No eligible completed participants exist for this campaign snapshot")

    per_user = (Decimal(row.funded_amount) / Decimal(len(eligible_user_ids))).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    if per_user <= 0:
        raise HTTPException(409, "Distribution pool is too small for the eligible cohort")
    distributed = per_user * Decimal(len(eligible_user_ids))
    for user_id in eligible_user_ids:
        db.add(RevenueShareRecipient(distribution_id=row.id, user_id=user_id, amount=per_user))
        db.add(LedgerEntry(user_id=user_id, campaign_id=row.campaign_id, asset_symbol=row.asset_symbol, amount=per_user, entry_type="REVENUE_SHARE", note=f"Funded community distribution: {row.title}"))
    row.recipient_count = len(eligible_user_ids); row.amount_per_recipient = per_user; row.distributed_amount = distributed; row.status = "EXECUTED"; row.executed_at = datetime.now(UTC)
    db.commit(); return serialize(row, db, user.id)
