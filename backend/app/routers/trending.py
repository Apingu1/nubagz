from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..challenge_models import Challenge, ChallengeOnchainProof
from ..db import get_db
from ..deps import get_current_user
from ..models import Campaign, Enrollment, Project, User
from .daily import campaign_is_eligible
from .trust import project_trust

router = APIRouter(prefix="/api/trending", tags=["trending"])
PUBLIC_PROJECT_STATUSES = {"LIVE", "APPROVED"}


@router.get("")
def trending_bagz(
    days: int = 7,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    days = max(1, min(days, 30))
    cutoff = datetime.now(UTC) - timedelta(days=days)
    completed_ids = {
        row[0]
        for row in db.query(Enrollment.campaign_id).filter(
            Enrollment.user_id == user.id,
            Enrollment.status == "COMPLETED",
        ).all()
    }
    rows = []
    campaigns = db.query(Campaign).filter(
        Campaign.status == "LIVE"
    ).order_by(Campaign.created_at.desc()).all()

    for campaign in campaigns:
        if campaign.id in completed_ids or not campaign_is_eligible(db, user, campaign):
            continue
        project = db.get(Project, campaign.project_id)
        if not project or project.status not in PUBLIC_PROJECT_STATUSES:
            continue

        recent_enrollments = db.query(func.count(Enrollment.id)).filter(
            Enrollment.campaign_id == campaign.id,
            Enrollment.enrolled_at >= cutoff,
        ).scalar() or 0
        recent_completions = db.query(func.count(Enrollment.id)).filter(
            Enrollment.campaign_id == campaign.id,
            Enrollment.status == "COMPLETED",
            Enrollment.completed_at >= cutoff,
        ).scalar() or 0
        recent_onchain = db.query(func.count(ChallengeOnchainProof.id)).join(
            Challenge, Challenge.id == ChallengeOnchainProof.challenge_id
        ).filter(
            Challenge.campaign_id == campaign.id,
            ChallengeOnchainProof.verified_at >= cutoff,
        ).scalar() or 0

        project_campaign_ids = [
            row[0]
            for row in db.query(Campaign.id).filter(Campaign.project_id == project.id).all()
        ]
        repeat_participants = 0
        if project_campaign_ids:
            recent_users = [
                row[0]
                for row in db.query(Enrollment.user_id).filter(
                    Enrollment.campaign_id.in_(project_campaign_ids),
                    Enrollment.status == "COMPLETED",
                    Enrollment.completed_at >= cutoff,
                ).all()
            ]
            repeat_participants = sum(1 for count in Counter(recent_users).values() if count >= 2)

        score = (
            int(recent_enrollments)
            + int(recent_completions) * 3
            + int(recent_onchain) * 2
            + int(repeat_participants) * 2
        )
        user_reward = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.user_share_pct) / Decimal("100")
        estimated_user_gbp = None
        if campaign.estimated_value_gbp is not None:
            estimated_user_gbp = Decimal(campaign.estimated_value_gbp) * Decimal(campaign.user_share_pct) / Decimal("100")
        trust = project_trust(project, db)
        quality_score = min(
            100,
            int(trust["score"])
            + min(15, int(recent_onchain) * 3)
            + min(10, repeat_participants * 2),
        )
        rows.append({
            "campaign_id": campaign.id,
            "title": campaign.title,
            "project_name": project.name,
            "symbol": project.symbol,
            "category": campaign.category,
            "reward_asset": campaign.reward_asset,
            "user_reward": str(user_reward),
            "estimated_value_gbp": str(estimated_user_gbp) if estimated_user_gbp is not None else None,
            "recent_enrollments": int(recent_enrollments),
            "recent_completions": int(recent_completions),
            "recent_onchain_verifications": int(recent_onchain),
            "repeat_participants": repeat_participants,
            "project_trust_score": int(trust["score"]),
            "project_trust_level": trust["level"],
            "trend_score": score,
            "quality_score": quality_score,
            "window_days": days,
            "why_trending": (
                f"{recent_enrollments} joins + {recent_completions} verified Bag completions + "
                f"{recent_onchain} on-chain verifications + {repeat_participants} repeat participants "
                f"in the last {days} days"
            ),
        })

    rows.sort(key=lambda item: (
        -item["trend_score"],
        -item["recent_onchain_verifications"],
        -item["repeat_participants"],
        -item["project_trust_score"],
        -(Decimal(item["estimated_value_gbp"]) if item["estimated_value_gbp"] else Decimal("0")),
        item["campaign_id"],
    ))
    return {
        "window_days": days,
        "bagz": rows[:20],
        "method": (
            "Organic trend score = recent joins + 3× verified Bag completions + "
            "2× verified on-chain actions + 2× repeat participants. Project Trust and tracked "
            "reward value are transparent quality tie-breakers. Paid featured placement does not "
            "increase the trend score or quality score."
        ),
    }
