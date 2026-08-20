from datetime import datetime, UTC
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Campaign, Project, Enrollment, LedgerEntry
from ..marketplace_models import BagBuilderPathway, BagBuilderAttribution
from .risk import evaluate_user

router = APIRouter(prefix="/api/builders", tags=["bagbuilder"])


class PathwayIn(BaseModel):
    campaign_id: int
    title: str = Field(min_length=4, max_length=160)
    summary: str = Field(min_length=20, max_length=4000)
    creator_share_pct: Decimal = Field(gt=0, le=25)


class DecisionIn(BaseModel):
    status: str


def pathway_metrics(row: BagBuilderPathway, db: Session):
    attributed = db.query(func.count(BagBuilderAttribution.id)).filter(
        BagBuilderAttribution.pathway_id == row.id
    ).scalar() or 0
    converted = db.query(func.count(BagBuilderAttribution.id)).join(
        Enrollment,
        (Enrollment.user_id == BagBuilderAttribution.user_id)
        & (Enrollment.campaign_id == BagBuilderAttribution.campaign_id),
    ).filter(
        BagBuilderAttribution.pathway_id == row.id,
        Enrollment.status == "COMPLETED",
    ).scalar() or 0
    return int(attributed), int(converted)


def serialize(row: BagBuilderPathway, db: Session):
    campaign = db.get(Campaign, row.campaign_id)
    project = db.get(Project, campaign.project_id) if campaign else None
    creator = db.get(User, row.creator_id)
    attributed_users, completed_conversions = pathway_metrics(row, db)
    return {
        "id": row.id,
        "campaign_id": row.campaign_id,
        "campaign_title": campaign.title if campaign else None,
        "project_name": project.name if project else None,
        "creator_id": row.creator_id,
        "creator_username": creator.username if creator else None,
        "title": row.title,
        "summary": row.summary,
        "creator_share_pct": str(row.creator_share_pct),
        "status": row.status,
        "attributed_users": attributed_users,
        "completed_conversions": completed_conversions,
        "created_at": row.created_at.isoformat(),
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
    }


@router.get("")
def approved_pathways(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(BagBuilderPathway).filter(
        BagBuilderPathway.status == "APPROVED"
    ).order_by(BagBuilderPathway.created_at.desc()).all()
    return [serialize(row, db) for row in rows]


@router.get("/mine")
def my_pathways(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(BagBuilderPathway).filter(
        BagBuilderPathway.creator_id == user.id
    ).order_by(BagBuilderPathway.created_at.desc()).all()
    return [serialize(row, db) for row in rows]


@router.get("/stats")
def my_builder_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    total_pathways = db.query(func.count(BagBuilderPathway.id)).filter(
        BagBuilderPathway.creator_id == user.id
    ).scalar() or 0
    approved_pathways = db.query(func.count(BagBuilderPathway.id)).filter(
        BagBuilderPathway.creator_id == user.id,
        BagBuilderPathway.status == "APPROVED",
    ).scalar() or 0
    attributed_users = db.query(func.count(BagBuilderAttribution.id)).join(
        BagBuilderPathway, BagBuilderPathway.id == BagBuilderAttribution.pathway_id
    ).filter(BagBuilderPathway.creator_id == user.id).scalar() or 0
    completed_conversions = db.query(func.count(BagBuilderAttribution.id)).join(
        BagBuilderPathway, BagBuilderPathway.id == BagBuilderAttribution.pathway_id
    ).join(
        Enrollment,
        (Enrollment.user_id == BagBuilderAttribution.user_id)
        & (Enrollment.campaign_id == BagBuilderAttribution.campaign_id),
    ).filter(
        BagBuilderPathway.creator_id == user.id,
        Enrollment.status == "COMPLETED",
    ).scalar() or 0
    earning_rows = db.query(
        LedgerEntry.asset_symbol,
        func.coalesce(func.sum(LedgerEntry.amount), 0),
    ).filter(
        LedgerEntry.user_id == user.id,
        LedgerEntry.entry_type == "BUILDER_SHARE",
    ).group_by(LedgerEntry.asset_symbol).order_by(LedgerEntry.asset_symbol.asc()).all()
    return {
        "total_pathways": int(total_pathways),
        "approved_pathways": int(approved_pathways),
        "attributed_users": int(attributed_users),
        "completed_conversions": int(completed_conversions),
        "earnings": [
            {"asset_symbol": asset, "amount": str(amount)} for asset, amount in earning_rows
        ],
    }


@router.get("/review")
def review_queue(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(BagBuilderPathway).join(
        Campaign, Campaign.id == BagBuilderPathway.campaign_id
    ).join(
        Project, Project.id == Campaign.project_id
    ).filter(
        Project.owner_id == user.id
    ).order_by(BagBuilderPathway.created_at.desc()).all()
    return [serialize(row, db) for row in rows]


@router.post("")
def create_pathway(data: PathwayIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, data.campaign_id)
    if not campaign or campaign.status != "LIVE":
        raise HTTPException(404, "Live campaign not found")
    project = db.get(Project, campaign.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project.owner_id == user.id:
        raise HTTPException(400, "Project owners cannot earn a BagBuilder share from their own campaign")
    trust = evaluate_user(db, user)
    if trust.trust_level == "RESTRICTED":
        raise HTTPException(403, "Restricted accounts cannot create reward-earning BagBuilder pathways")
    if data.creator_share_pct > Decimal(campaign.nubagz_share_pct):
        raise HTTPException(400, "BagBuilder share cannot exceed the NuBagz platform share")
    existing = db.query(BagBuilderPathway).filter(
        BagBuilderPathway.campaign_id == campaign.id,
        BagBuilderPathway.creator_id == user.id,
        BagBuilderPathway.status != "REJECTED",
    ).first()
    if existing:
        raise HTTPException(409, "You already have an active or pending pathway for this campaign")
    row = BagBuilderPathway(
        campaign_id=campaign.id,
        creator_id=user.id,
        title=data.title,
        summary=data.summary,
        creator_share_pct=data.creator_share_pct,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize(row, db)


@router.patch("/{pathway_id}")
def decide_pathway(pathway_id: int, data: DecisionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(BagBuilderPathway, pathway_id)
    campaign = db.get(Campaign, row.campaign_id) if row else None
    project = db.get(Project, campaign.project_id) if campaign else None
    if not row or not project or project.owner_id != user.id:
        raise HTTPException(403, "Only the project owner can review this pathway")
    status = data.status.upper()
    if status not in {"APPROVED", "REJECTED"}:
        raise HTTPException(400, "Invalid pathway status")
    if status == "APPROVED":
        creator = db.get(User, row.creator_id)
        if not creator or creator.id == project.owner_id:
            raise HTTPException(409, "This pathway is not eligible for BagBuilder rewards")
        trust = evaluate_user(db, creator)
        if trust.trust_level == "RESTRICTED":
            raise HTTPException(409, "This BagBuilder is restricted and cannot be approved for reward sharing")
        if Decimal(row.creator_share_pct) > Decimal(campaign.nubagz_share_pct):
            raise HTTPException(409, "The pathway share no longer fits inside the campaign's NuBagz share")
    row.status = status
    row.approved_by_id = user.id
    row.approved_at = datetime.now(UTC) if status == "APPROVED" else None
    db.commit()
    return serialize(row, db)


@router.post("/{pathway_id}/start")
def start_pathway(pathway_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(BagBuilderPathway, pathway_id)
    if not row or row.status != "APPROVED":
        raise HTTPException(404, "Approved BagBuilder pathway not found")
    if row.creator_id == user.id:
        raise HTTPException(400, "BagBuilders cannot self-attribute their own pathway")
    existing = db.query(BagBuilderAttribution).filter(
        BagBuilderAttribution.user_id == user.id,
        BagBuilderAttribution.campaign_id == row.campaign_id,
    ).first()
    if existing:
        if existing.pathway_id != row.id:
            raise HTTPException(409, "A BagBuilder pathway is already attributed for this campaign")
        return {"ok": True, "pathway_id": row.id, "campaign_id": row.campaign_id}
    trust = evaluate_user(db, user)
    if trust.trust_level == "RESTRICTED":
        raise HTTPException(403, "Restricted accounts cannot start reward-attributed BagBuilder pathways")
    enrollment = db.query(Enrollment).filter(
        Enrollment.user_id == user.id,
        Enrollment.campaign_id == row.campaign_id,
    ).first()
    if enrollment:
        raise HTTPException(409, "Choose a BagBuilder pathway before joining the campaign; attribution cannot be added retroactively")
    db.add(BagBuilderAttribution(
        pathway_id=row.id,
        campaign_id=row.campaign_id,
        user_id=user.id,
    ))
    db.commit()
    return {"ok": True, "pathway_id": row.id, "campaign_id": row.campaign_id}
