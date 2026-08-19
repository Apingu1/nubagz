from collections import defaultdict
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Project, Campaign, Enrollment, LedgerEntry
from ..economy_models import CampaignFunding
from ..marketplace_models import BagBuilderAttribution

router = APIRouter(prefix="/api/project-analytics", tags=["project-analytics"])


def campaign_metrics(db: Session, campaign: Campaign):
    enrollments = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == campaign.id).scalar() or 0
    completions = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == campaign.id, Enrollment.status == "COMPLETED").scalar() or 0
    funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign.id).first()
    ledger_rows = db.query(LedgerEntry).filter(LedgerEntry.campaign_id == campaign.id).all()
    distributed = sum((Decimal(row.amount) for row in ledger_rows), Decimal("0"))
    referral_conversions = db.query(func.count(Enrollment.id)).join(User, User.id == Enrollment.user_id).filter(Enrollment.campaign_id == campaign.id, Enrollment.status == "COMPLETED", User.referred_by_id.isnot(None)).scalar() or 0
    builder_conversions = db.query(func.count(Enrollment.id)).join(BagBuilderAttribution, (BagBuilderAttribution.user_id == Enrollment.user_id) & (BagBuilderAttribution.campaign_id == Enrollment.campaign_id)).filter(Enrollment.campaign_id == campaign.id, Enrollment.status == "COMPLETED").scalar() or 0
    completion_rate = (Decimal(completions) / Decimal(enrollments) * Decimal("100")) if enrollments else Decimal("0")
    cost_per_completion = (distributed / Decimal(completions)) if completions else None
    required = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.max_users)
    return {
        "campaign_id": campaign.id,
        "title": campaign.title,
        "status": campaign.status,
        "reward_asset": campaign.reward_asset,
        "max_users": campaign.max_users,
        "enrollments": int(enrollments),
        "completions": int(completions),
        "completion_rate_pct": str(completion_rate.quantize(Decimal("0.01"))),
        "gross_reward_per_user": str(campaign.gross_reward_per_user),
        "maximum_reward_obligation": str(required),
        "funding_status": funding.status if funding else "UNFUNDED",
        "verified_funding": str(funding.verified_amount) if funding else "0",
        "distributed_total": str(distributed),
        "cost_per_completed_participant": str(cost_per_completion) if cost_per_completion is not None else None,
        "referral_conversions": int(referral_conversions),
        "bagbuilder_conversions": int(builder_conversions),
    }


def project_payload(db: Session, project: Project):
    campaigns = db.query(Campaign).filter(Campaign.project_id == project.id).order_by(Campaign.created_at.desc()).all()
    rows = [campaign_metrics(db, campaign) for campaign in campaigns]
    distributions = defaultdict(Decimal)
    for row in rows:
        distributions[row["reward_asset"]] += Decimal(row["distributed_total"])
    enrollments = sum(row["enrollments"] for row in rows)
    completions = sum(row["completions"] for row in rows)
    return {
        "project_id": project.id,
        "name": project.name,
        "symbol": project.symbol,
        "status": project.status,
        "campaign_count": len(rows),
        "live_campaigns": sum(1 for row in rows if row["status"] == "LIVE"),
        "enrollments": enrollments,
        "completions": completions,
        "completion_rate_pct": str((Decimal(completions) / Decimal(enrollments) * Decimal("100")).quantize(Decimal("0.01"))) if enrollments else "0.00",
        "unique_completed_participants": db.query(func.count(func.distinct(Enrollment.user_id))).join(Campaign, Campaign.id == Enrollment.campaign_id).filter(Campaign.project_id == project.id, Enrollment.status == "COMPLETED").scalar() or 0,
        "distributed_by_asset": [{"asset": asset, "amount": str(amount)} for asset, amount in sorted(distributions.items())],
        "campaigns": rows,
    }


@router.get("")
def my_project_analytics(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    projects = db.query(Project).filter(Project.owner_id == user.id).order_by(Project.created_at.desc()).all()
    payloads = [project_payload(db, project) for project in projects]
    return {
        "projects": payloads,
        "totals": {
            "projects": len(payloads),
            "campaigns": sum(p["campaign_count"] for p in payloads),
            "enrollments": sum(p["enrollments"] for p in payloads),
            "completions": sum(p["completions"] for p in payloads),
            "unique_completed_participants": len({row[0] for row in db.query(Enrollment.user_id).join(Campaign, Campaign.id == Enrollment.campaign_id).join(Project, Project.id == Campaign.project_id).filter(Project.owner_id == user.id, Enrollment.status == "COMPLETED").distinct().all()}),
        },
        "principle": "NuBagz analytics report verified participation and reward distribution, not advertising impressions.",
    }


@router.get("/projects/{project_id}")
def one_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = db.get(Project, project_id)
    if not project or project.owner_id != user.id:
        raise HTTPException(404, "Project not found")
    return project_payload(db, project)
