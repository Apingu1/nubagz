from datetime import datetime, UTC, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Project, Campaign, Enrollment
from ..engagement_models import ProjectReview
from .daily import campaign_is_eligible

router = APIRouter(prefix="/api/trending", tags=["trending"])


@router.get("")
def trending_bagz(days: int = 7, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    days = max(1, min(days, 30))
    cutoff = datetime.now(UTC) - timedelta(days=days)
    completed_ids = {row[0] for row in db.query(Enrollment.campaign_id).filter(Enrollment.user_id == user.id, Enrollment.status == "COMPLETED").all()}
    rows = []
    campaigns = db.query(Campaign).filter(Campaign.status == "LIVE").order_by(Campaign.created_at.desc()).all()
    for campaign in campaigns:
        if campaign.id in completed_ids or not campaign_is_eligible(db, user, campaign):
            continue
        project = db.get(Project, campaign.project_id)
        if not project or project.status != "APPROVED":
            continue
        recent_enrollments = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == campaign.id, Enrollment.enrolled_at >= cutoff).scalar() or 0
        recent_completions = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == campaign.id, Enrollment.status == "COMPLETED", Enrollment.completed_at >= cutoff).scalar() or 0
        recent_reviews = db.query(func.count(ProjectReview.id)).filter(ProjectReview.project_id == project.id, ProjectReview.status == "PUBLISHED", ProjectReview.updated_at >= cutoff).scalar() or 0
        score = int(recent_enrollments) + int(recent_completions) * 3 + int(recent_reviews) * 2
        user_reward = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.user_share_pct) / Decimal("100")
        rows.append({
            "campaign_id":campaign.id,"title":campaign.title,"project_name":project.name,"symbol":project.symbol,
            "category":campaign.category,"reward_asset":campaign.reward_asset,"user_reward":str(user_reward),
            "recent_enrollments":int(recent_enrollments),"recent_completions":int(recent_completions),"recent_verified_reviews":int(recent_reviews),
            "trend_score":score,"window_days":days,
            "why_trending":f"{recent_enrollments} joins + {recent_completions} completions + {recent_reviews} verified reviews in the last {days} days",
        })
    rows.sort(key=lambda item: (-item["trend_score"], -item["recent_completions"], -item["recent_enrollments"], item["campaign_id"]))
    return {"window_days":days,"bagz":rows[:20],"method":"Trend score = recent enrollments + 3× recent completions + 2× verified participant reviews. Paid featured placement does not increase this score."}
