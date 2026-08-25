from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from .challenge_models import Challenge
from .economy_models import CampaignFunding
from .models import Campaign, Mission, Project

PUBLIC_PROJECT_STATUSES = {"LIVE", "APPROVED"}


def required_amount(campaign: Campaign) -> Decimal:
    return Decimal(campaign.gross_reward_per_user) * Decimal(campaign.max_users)


def active_work_count(db: Session, campaign_id: int) -> int:
    return int(
        db.query(func.count(Challenge.id))
        .filter(Challenge.campaign_id == campaign_id, Challenge.status == "ACTIVE")
        .scalar()
        or 0
    )


def legacy_mission_count(db: Session, campaign_id: int) -> int:
    return int(
        db.query(func.count(Mission.id))
        .filter(Mission.campaign_id == campaign_id)
        .scalar()
        or 0
    )


def funding_record(db: Session, campaign_id: int) -> CampaignFunding | None:
    return (
        db.query(CampaignFunding)
        .filter(CampaignFunding.campaign_id == campaign_id)
        .first()
    )


def fully_funded(campaign: Campaign, funding: CampaignFunding | None) -> bool:
    return bool(
        funding
        and funding.status == "VERIFIED"
        and Decimal(funding.verified_amount or 0) >= required_amount(campaign)
    )


def publication_blockers(
    db: Session,
    campaign: Campaign,
    funding: CampaignFunding | None = None,
) -> list[str]:
    funding = funding if funding is not None else funding_record(db, campaign.id)
    project = db.get(Project, campaign.project_id)
    blockers: list[str] = []

    if not project or project.status not in PUBLIC_PROJECT_STATUSES:
        blockers.append("PROJECT_NOT_PUBLIC")
    if active_work_count(db, campaign.id) <= 0:
        blockers.append("NO_ACTIVE_BAG_WORK")
    if not funding or funding.status != "VERIFIED":
        blockers.append("FUNDING_NOT_VERIFIED")
    elif Decimal(funding.verified_amount or 0) < required_amount(campaign):
        blockers.append("FUNDING_BELOW_MAX_LIABILITY")

    if campaign.status == "PAUSED":
        blockers.append("BAG_PAUSED")
    elif campaign.status == "SUSPENDED":
        blockers.append("BAG_SUSPENDED")
    elif campaign.status == "ARCHIVED":
        blockers.append("BAG_ARCHIVED")
    elif campaign.status not in {"LIVE", "DRAFT", "PENDING"}:
        blockers.append("BAG_NOT_LIVE")

    return blockers


def reconcile_campaign_publication(
    db: Session,
    campaign: Campaign,
    funding: CampaignFunding | None = None,
) -> bool:
    """Promote an objectively ready draft Bag to LIVE.

    This deliberately never changes PAUSED/SUSPENDED/ARCHIVED states. Those are
    explicit creator/moderation decisions. It exists to repair older databases
    where funding was already VERIFIED before automatic publication was added.
    """
    if campaign.status not in {"DRAFT", "PENDING"}:
        return False

    funding = funding if funding is not None else funding_record(db, campaign.id)
    project = db.get(Project, campaign.project_id)
    if (
        project
        and project.status in PUBLIC_PROJECT_STATUSES
        and active_work_count(db, campaign.id) > 0
        and fully_funded(campaign, funding)
    ):
        campaign.status = "LIVE"
        return True
    return False


def reconcile_verified_drafts(db: Session, campaign_ids: list[int] | None = None) -> int:
    q = db.query(Campaign).filter(Campaign.status.in_({"DRAFT", "PENDING"}))
    if campaign_ids is not None:
        q = q.filter(Campaign.id.in_(campaign_ids or [-1]))
    changed = 0
    for campaign in q.all():
        if reconcile_campaign_publication(db, campaign):
            changed += 1
    if changed:
        db.commit()
    return changed
