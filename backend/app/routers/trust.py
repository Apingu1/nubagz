from datetime import datetime, UTC
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Campaign, Enrollment
from ..economy_models import CampaignFunding

router = APIRouter(prefix="/api/trust", tags=["trust"])


def project_trust(project: Project, db: Session):
    campaigns = db.query(Campaign).filter(Campaign.project_id == project.id).all()
    campaign_ids = [c.id for c in campaigns]
    approved_points = 25 if project.status == "APPROVED" else 0

    verified_funding = 0
    if campaign_ids:
        verified_funding = db.query(func.count(CampaignFunding.id)).filter(CampaignFunding.campaign_id.in_(campaign_ids), CampaignFunding.status == "VERIFIED").scalar() or 0
    funding_ratio = Decimal(verified_funding) / Decimal(len(campaigns)) if campaigns else Decimal("0")
    funding_points = int(funding_ratio * Decimal("25"))

    enrollments = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id.in_(campaign_ids)).scalar() or 0 if campaign_ids else 0
    completions = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id.in_(campaign_ids), Enrollment.status == "COMPLETED").scalar() or 0 if campaign_ids else 0
    completion_rate = Decimal(completions) / Decimal(enrollments) if enrollments else Decimal("0")
    completion_points = min(20, int(completion_rate * Decimal("20")))

    transparency_points = 0
    if project.website:
        transparency_points += 8
    if project.treasury_address:
        transparency_points += 7

    created = project.created_at.replace(tzinfo=UTC) if project.created_at.tzinfo is None else project.created_at
    age_days = max(0, (datetime.now(UTC) - created).days)
    age_points = min(15, age_days // 7)

    score = min(100, approved_points + funding_points + completion_points + transparency_points + age_points)
    level = "LOW SIGNAL"
    if score >= 80: level = "STRONG"
    elif score >= 60: level = "ESTABLISHED"
    elif score >= 40: level = "DEVELOPING"
    elif score >= 20: level = "EARLY"
    return {
        "project_id": project.id,
        "name": project.name,
        "symbol": project.symbol,
        "score": score,
        "level": level,
        "factors": {
            "approval": approved_points,
            "verified_funding": funding_points,
            "completion_quality": completion_points,
            "transparency": transparency_points,
            "age": age_points,
        },
        "metrics": {
            "campaigns": len(campaigns),
            "verified_funded_campaigns": int(verified_funding),
            "participants": int(enrollments),
            "completions": int(completions),
            "completion_rate_pct": str(completion_rate * Decimal("100")),
            "age_days": age_days,
        },
        "disclaimer": "NuBagz Trust Score is an internal participation and transparency risk signal. It is not an endorsement, audit, guarantee, or investment recommendation.",
    }


@router.get("/projects")
def trust_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).filter(Project.status == "APPROVED").order_by(Project.created_at.desc()).all()
    return sorted([project_trust(p, db) for p in projects], key=lambda item: item["score"], reverse=True)


@router.get("/projects/{project_id}")
def trust_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project_trust(project, db)
