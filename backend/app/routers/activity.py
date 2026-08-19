from datetime import datetime, UTC
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Project, Campaign, Enrollment
from ..economy_models import BagDrop, BagDropClaim
from ..engagement_models import ProjectReview

router = APIRouter(prefix="/api/activity", tags=["activity-feed"])


def iso(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


@router.get("")
def activity_feed(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    limit = max(1, min(limit, 100))
    events = []

    completions = db.query(Enrollment).filter(Enrollment.status == "COMPLETED", Enrollment.completed_at.isnot(None)).order_by(Enrollment.completed_at.desc()).limit(limit).all()
    for enrollment in completions:
        user = db.get(User, enrollment.user_id)
        campaign = db.get(Campaign, enrollment.campaign_id)
        project = db.get(Project, campaign.project_id) if campaign else None
        if not user or not campaign or not project or project.status == "SUSPENDED":
            continue
        events.append({
            "event_type":"BAG_COMPLETED","username":user.username,
            "headline":f"{user.username} completed {campaign.title}",
            "detail":f"Bagged {campaign.reward_asset} through a funded {campaign.category.title()} pathway from {project.name}.",
            "project_name":project.name,"campaign_id":campaign.id,"link_path":f"/app/bagz/{campaign.id}",
            "occurred_at":iso(enrollment.completed_at),
        })

    claims = db.query(BagDropClaim).order_by(BagDropClaim.claimed_at.desc()).limit(limit).all()
    for claim in claims:
        user = db.get(User, claim.user_id); drop = db.get(BagDrop, claim.drop_id); project = db.get(Project, drop.project_id) if drop else None
        if not user or not drop or not project or project.status == "SUSPENDED":
            continue
        events.append({
            "event_type":"BAGDROP_CLAIMED","username":user.username,
            "headline":f"{user.username} opened {drop.title}",
            "detail":f"Claimed a verified {drop.rarity.title()} BagDrop from {project.name}.",
            "project_name":project.name,"campaign_id":None,"link_path":"/app/drops",
            "occurred_at":iso(claim.claimed_at),
        })

    reviews = db.query(ProjectReview).filter(ProjectReview.status == "PUBLISHED").order_by(ProjectReview.updated_at.desc()).limit(limit).all()
    for review in reviews:
        user = db.get(User, review.user_id); project = db.get(Project, review.project_id)
        if not user or not project or project.status == "SUSPENDED":
            continue
        events.append({
            "event_type":"PROJECT_REVIEWED","username":user.username,
            "headline":f"{user.username} reviewed {project.name}",
            "detail":f"Verified participant experience rating: {review.rating}/5.",
            "project_name":project.name,"campaign_id":None,"link_path":"/app/reviews",
            "occurred_at":iso(review.updated_at),
        })

    events.sort(key=lambda row: row["occurred_at"] or "", reverse=True)
    return {
        "events": events[:limit],
        "privacy":"The community feed uses public NuBagz usernames and participation events only. It never exposes emails, wallet addresses, payout destinations or private account balances.",
    }
