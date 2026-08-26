from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..economy_models import BagDrop, BagDropClaim
from ..models import Campaign, Enrollment, Project, User

router = APIRouter(prefix="/api/activity", tags=["activity-feed"])
EVENT_TYPES = {"BAG_COMPLETED", "BAGDROP_CLAIMED"}
PUBLIC_PROJECT_STATUSES = {"LIVE", "APPROVED"}


def iso(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def visible_user(user: User | None) -> bool:
    return bool(user and user.is_active)


def visible_project(project: Project | None) -> bool:
    return bool(project and project.status in PUBLIC_PROJECT_STATUSES)


@router.get("")
def activity_feed(
    limit: int = Query(default=50, ge=1, le=100),
    event_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    requested = event_type.upper() if event_type else None
    if requested and requested not in EVENT_TYPES:
        raise HTTPException(400, f"event_type must be one of {', '.join(sorted(EVENT_TYPES))}")
    events = []

    if requested in {None, "BAG_COMPLETED"}:
        completions = db.query(Enrollment).filter(
            Enrollment.status == "COMPLETED",
            Enrollment.completed_at.isnot(None),
        ).order_by(Enrollment.completed_at.desc()).limit(limit).all()
        for enrollment in completions:
            user = db.get(User, enrollment.user_id)
            campaign = db.get(Campaign, enrollment.campaign_id)
            project = db.get(Project, campaign.project_id) if campaign else None
            if not visible_user(user) or not visible_project(project) or not campaign or campaign.status not in {"LIVE", "COMPLETED"}:
                continue
            events.append({
                "event_id": f"completion:{enrollment.id}",
                "event_type": "BAG_COMPLETED",
                "username": user.username,
                "headline": f"{user.username} completed {campaign.title}",
                "detail": f"Bagged {campaign.reward_asset} through verified Bag Work from {project.name}.",
                "project_name": project.name,
                "campaign_id": campaign.id,
                "link_path": f"/app/bagz/{campaign.id}",
                "occurred_at": iso(enrollment.completed_at),
            })

    if requested in {None, "BAGDROP_CLAIMED"}:
        claims = db.query(BagDropClaim).order_by(BagDropClaim.claimed_at.desc()).limit(limit).all()
        for claim in claims:
            user = db.get(User, claim.user_id)
            drop = db.get(BagDrop, claim.drop_id)
            project = db.get(Project, drop.project_id) if drop else None
            if not visible_user(user) or not visible_project(project) or not drop or drop.funding_status != "VERIFIED" or drop.status not in {"LIVE", "COMPLETED"}:
                continue
            events.append({
                "event_id": f"bagdrop:{claim.id}",
                "event_type": "BAGDROP_CLAIMED",
                "username": user.username,
                "headline": f"{user.username} opened {drop.title}",
                "detail": f"Claimed a verified {drop.rarity.title()} BagDrop from {project.name}.",
                "project_name": project.name,
                "campaign_id": None,
                "link_path": "/app/drops",
                "occurred_at": iso(claim.claimed_at),
            })

    events.sort(key=lambda row: row["occurred_at"] or "", reverse=True)
    return {
        "events": events[:limit],
        "selected_event_type": requested,
        "available_event_types": sorted(EVENT_TYPES),
        "privacy": "The community feed uses public NuBagz usernames and verified participation events only. It never exposes emails, wallet addresses, payout destinations or private account balances, and moderated/suspended content is removed from feed visibility.",
    }
