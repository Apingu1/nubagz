from datetime import datetime, UTC
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Campaign, Project, Enrollment
from ..marketplace_models import BagBuilderPathway, BagBuilderAttribution

router = APIRouter(prefix="/api/builders", tags=["bagbuilder"])


class PathwayIn(BaseModel):
    campaign_id: int
    title: str = Field(min_length=4, max_length=160)
    summary: str = Field(min_length=20, max_length=4000)
    creator_share_pct: Decimal = Field(gt=0, le=25)


class DecisionIn(BaseModel):
    status: str


def serialize(row: BagBuilderPathway, db: Session):
    campaign = db.get(Campaign, row.campaign_id)
    project = db.get(Project, campaign.project_id) if campaign else None
    creator = db.get(User, row.creator_id)
    return {
        "id": row.id, "campaign_id": row.campaign_id, "campaign_title": campaign.title if campaign else None,
        "project_name": project.name if project else None, "creator_id": row.creator_id,
        "creator_username": creator.username if creator else None, "title": row.title, "summary": row.summary,
        "creator_share_pct": str(row.creator_share_pct), "status": row.status,
        "created_at": row.created_at.isoformat(), "approved_at": row.approved_at.isoformat() if row.approved_at else None,
    }


@router.get("")
def approved_pathways(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(BagBuilderPathway).filter(BagBuilderPathway.status == "APPROVED").order_by(BagBuilderPathway.created_at.desc()).all()
    return [serialize(row, db) for row in rows]


@router.get("/mine")
def my_pathways(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(BagBuilderPathway).filter(BagBuilderPathway.creator_id == user.id).order_by(BagBuilderPathway.created_at.desc()).all()
    return [serialize(row, db) for row in rows]


@router.get("/review")
def review_queue(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(BagBuilderPathway).join(Campaign, Campaign.id == BagBuilderPathway.campaign_id).join(Project, Project.id == Campaign.project_id).filter(Project.owner_id == user.id).order_by(BagBuilderPathway.created_at.desc()).all()
    return [serialize(row, db) for row in rows]


@router.post("")
def create_pathway(data: PathwayIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, data.campaign_id)
    if not campaign or campaign.status != "LIVE":
        raise HTTPException(404, "Live campaign not found")
    if data.creator_share_pct > Decimal(campaign.nubagz_share_pct):
        raise HTTPException(400, "BagBuilder share cannot exceed the NuBagz platform share")
    row = BagBuilderPathway(campaign_id=campaign.id, creator_id=user.id, title=data.title, summary=data.summary, creator_share_pct=data.creator_share_pct)
    db.add(row); db.commit(); db.refresh(row)
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
    row.status = status; row.approved_by_id = user.id
    row.approved_at = datetime.now(UTC) if status == "APPROVED" else None
    db.commit(); return serialize(row, db)


@router.post("/{pathway_id}/start")
def start_pathway(pathway_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(BagBuilderPathway, pathway_id)
    if not row or row.status != "APPROVED":
        raise HTTPException(404, "Approved BagBuilder pathway not found")
    if row.creator_id == user.id:
        raise HTTPException(400, "BagBuilders cannot self-attribute their own pathway")
    enrollment = db.query(Enrollment).filter(Enrollment.user_id == user.id, Enrollment.campaign_id == row.campaign_id).first()
    if enrollment and enrollment.status == "COMPLETED":
        raise HTTPException(409, "This campaign was already completed before BagBuilder attribution")
    existing = db.query(BagBuilderAttribution).filter(BagBuilderAttribution.user_id == user.id, BagBuilderAttribution.campaign_id == row.campaign_id).first()
    if existing:
        if existing.pathway_id != row.id:
            raise HTTPException(409, "A BagBuilder pathway is already attributed for this campaign")
        return {"ok": True, "pathway_id": row.id, "campaign_id": row.campaign_id}
    db.add(BagBuilderAttribution(pathway_id=row.id, campaign_id=row.campaign_id, user_id=user.id)); db.commit()
    return {"ok": True, "pathway_id": row.id, "campaign_id": row.campaign_id}
