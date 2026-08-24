from collections import defaultdict
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Project, Campaign, Enrollment, LedgerEntry
from ..economy_models import CampaignFunding
from ..economy import CAMPAIGN_SETTLEMENT_ENTRY_TYPES, campaign_distributed_total

router = APIRouter(prefix="/api/project-analytics", tags=["project-analytics"])


def campaign_metrics(db: Session, campaign: Campaign):
    enrollments = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == campaign.id).scalar() or 0
    completions = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == campaign.id, Enrollment.status == "COMPLETED").scalar() or 0
    unique_completed = db.query(func.count(func.distinct(Enrollment.user_id))).filter(Enrollment.campaign_id == campaign.id, Enrollment.status == "COMPLETED").scalar() or 0
    funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign.id).first()

    ledger_rows = db.query(LedgerEntry).filter(LedgerEntry.campaign_id == campaign.id).all()
    settlement_rows = [row for row in ledger_rows if row.entry_type in CAMPAIGN_SETTLEMENT_ENTRY_TYPES]
    non_campaign_rows = [row for row in ledger_rows if row.entry_type not in CAMPAIGN_SETTLEMENT_ENTRY_TYPES]
    distributed = campaign_distributed_total(db, campaign.id)
    linked_non_campaign = sum((Decimal(row.amount) for row in non_campaign_rows), Decimal("0"))
    breakdown = defaultdict(Decimal)
    for row in settlement_rows:
        breakdown[row.entry_type] += Decimal(row.amount)

    referral_conversions = db.query(func.count(Enrollment.id)).join(User, User.id == Enrollment.user_id).filter(Enrollment.campaign_id == campaign.id, Enrollment.status == "COMPLETED", User.referred_by_id.isnot(None)).scalar() or 0
    completion_rate = (Decimal(completions) / Decimal(enrollments) * Decimal("100")) if enrollments else Decimal("0")
    cost_per_completion = (distributed / Decimal(completions)) if completions else None
    required = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.max_users)
    verified = Decimal(funding.verified_amount) if funding and funding.status == "VERIFIED" else Decimal("0")
    remaining = max(Decimal("0"), verified - distributed)
    utilization = (distributed / verified * Decimal("100")) if verified > 0 else Decimal("0")
    reconciled = bool(funding and funding.status == "VERIFIED" and distributed <= verified)

    return {
        "campaign_id": campaign.id,
        "title": campaign.title,
        "status": campaign.status,
        "reward_asset": campaign.reward_asset,
        "max_users": campaign.max_users,
        "enrollments": int(enrollments),
        "completions": int(completions),
        "unique_completed_participants": int(unique_completed),
        "completion_rate_pct": str(completion_rate.quantize(Decimal("0.01"))),
        "gross_reward_per_user": str(campaign.gross_reward_per_user),
        "maximum_reward_obligation": str(required),
        "funding_status": funding.status if funding else "UNFUNDED",
        "verified_funding": str(verified),
        "remaining_verified_funding": str(remaining),
        "funding_utilization_pct": str(utilization.quantize(Decimal("0.01"))),
        "distributed_total": str(distributed),
        "settlement_breakdown": [{"entry_type": key, "amount": str(amount)} for key, amount in sorted(breakdown.items())],
        "linked_non_campaign_distribution_total": str(linked_non_campaign),
        "reconciled": reconciled,
        "cost_per_completed_participant": str(cost_per_completion) if cost_per_completion is not None else None,
        "referral_conversions": int(referral_conversions),
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
        "all_campaigns_reconciled": all(row["reconciled"] for row in rows if row["funding_status"] == "VERIFIED"),
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
        "principle": "NuBagz analytics report verified participation and reconciled campaign settlement entries. Referrals remain the user-acquisition reward mechanism; the retired BagBuilder pathway no longer participates in new settlement.",
    }


@router.get("/projects/{project_id}")
def one_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = db.get(Project, project_id)
    if not project or project.owner_id != user.id:
        raise HTTPException(404, "Project not found")
    return project_payload(db, project)
