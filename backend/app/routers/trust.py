from datetime import datetime, UTC
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Project, Campaign, Enrollment
from ..economy_models import CampaignFunding

router = APIRouter(prefix="/api/trust", tags=["trust"])
SCORE_VERSION = "1.0"


def project_trust(project: Project, db: Session):
    campaigns = db.query(Campaign).filter(Campaign.project_id == project.id).all()
    campaign_ids = [c.id for c in campaigns]
    approved_points = 25 if project.status == "APPROVED" else 0

    fully_funded = 0
    for campaign in campaigns:
        funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign.id, CampaignFunding.status == "VERIFIED").first()
        required = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.max_users)
        if funding and Decimal(funding.verified_amount) >= required:
            fully_funded += 1
    funding_ratio = Decimal(fully_funded) / Decimal(len(campaigns)) if campaigns else Decimal("0")
    funding_points = min(25, int(funding_ratio * Decimal("25")))

    if campaign_ids:
        enrollments = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id.in_(campaign_ids)).scalar() or 0
        completions = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id.in_(campaign_ids), Enrollment.status == "COMPLETED").scalar() or 0
    else:
        enrollments = completions = 0
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

    factors = {
        "approval": approved_points,
        "verified_funding": funding_points,
        "completion_quality": completion_points,
        "transparency": transparency_points,
        "age": age_points,
    }
    score = min(100, sum(factors.values()))
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
        "factors": factors,
        "metrics": {
            "campaigns": len(campaigns),
            "verified_funded_campaigns": fully_funded,
            "participants": int(enrollments),
            "completions": int(completions),
            "completion_rate_pct": str(completion_rate * Decimal("100")),
            "age_days": age_days,
        },
        "score_version": SCORE_VERSION,
        "calculated_at": datetime.now(UTC).isoformat(),
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
