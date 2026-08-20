from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Campaign, Project
from ..economy_models import CampaignAccessRule

router = APIRouter(prefix="/api/access", tags=["access"])

TIER_DEFINITIONS = [
    {"name": "STARTER", "min_score": 0, "max_score": 199, "benefits": ["Starter Bagz", "Learn & Earn", "Daily Earn"]},
    {"name": "EXPLORER", "min_score": 200, "max_score": 399, "benefits": ["Higher-value Bagz", "BagDrops", "Explorer-gated campaigns"]},
    {"name": "CONTRIBUTOR", "min_score": 400, "max_score": 599, "benefits": ["Contributor campaigns", "Creator and bounty opportunities", "Higher-trust participation"]},
    {"name": "PREMIUM", "min_score": 600, "max_score": 799, "benefits": ["Premium campaigns", "Priority beta and testing opportunities", "Higher-value reward pools"]},
    {"name": "ELITE", "min_score": 800, "max_score": 1000, "benefits": ["Elite campaigns", "High-trust opportunities", "Top reputation access"]},
]


class AccessRuleIn(BaseModel):
    min_bag_score: int = Field(ge=0, le=1000)


def tier_definition(score: int):
    clamped = max(0, min(1000, score))
    return next(item for item in TIER_DEFINITIONS if item["min_score"] <= clamped <= item["max_score"])


def tier(score: int):
    current = tier_definition(score)
    idx = TIER_DEFINITIONS.index(current)
    next_score = TIER_DEFINITIONS[idx + 1]["min_score"] if idx + 1 < len(TIER_DEFINITIONS) else None
    return current["name"], next_score


def access_payload(campaign: Campaign, user: User, db: Session):
    rule = db.query(CampaignAccessRule).filter(CampaignAccessRule.campaign_id == campaign.id).first()
    minimum = rule.min_bag_score if rule else 0
    eligible = user.bag_score >= minimum
    required_tier = tier_definition(minimum)["name"] if minimum else "STARTER"
    current_tier = tier_definition(user.bag_score)
    shortfall = max(0, minimum - user.bag_score)
    reason = None if eligible else f"BagScore {minimum}+ required. You need {shortfall} more points."
    return {
        "campaign_id": campaign.id,
        "min_bag_score": minimum,
        "required_tier": required_tier,
        "eligible": eligible,
        "your_bag_score": user.bag_score,
        "your_tier": current_tier["name"],
        "shortfall": shortfall,
        "reason": reason,
        "applies_to": "NEW_ENROLLMENTS",
    }


@router.get("/tiers")
def tiers():
    return {"tiers": TIER_DEFINITIONS, "principle": "BagScore measures participation reputation, never deposited wealth."}


@router.get("/me")
def my_access(user: User = Depends(get_current_user)):
    current = tier_definition(user.bag_score)
    idx = TIER_DEFINITIONS.index(current)
    next_tier = TIER_DEFINITIONS[idx + 1] if idx + 1 < len(TIER_DEFINITIONS) else None
    return {
        "bag_score": user.bag_score,
        "tier": current["name"],
        "tier_min_score": current["min_score"],
        "tier_max_score": current["max_score"],
        "benefits": current["benefits"],
        "next_tier": next_tier["name"] if next_tier else None,
        "next_tier_score": next_tier["min_score"] if next_tier else None,
        "points_to_next": max(0, next_tier["min_score"] - user.bag_score) if next_tier else 0,
        "tiers": TIER_DEFINITIONS,
        "principle": "BagScore unlocks opportunities through genuine participation; depositing money does not increase it.",
    }


@router.get("/campaigns/{campaign_id}")
def campaign_access(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    return access_payload(campaign, user, db)


@router.post("/campaigns/{campaign_id}")
def set_campaign_access(campaign_id: int, data: AccessRuleIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, campaign_id)
    project = db.get(Project, campaign.project_id) if campaign else None
    if not campaign or not project or (project.owner_id != user.id and user.role != "ADMIN"):
        raise HTTPException(403, "You do not manage this campaign")
    rule = db.query(CampaignAccessRule).filter(CampaignAccessRule.campaign_id == campaign_id).first()
    if not rule:
        rule = CampaignAccessRule(campaign_id=campaign_id, updated_by_id=user.id)
        db.add(rule)
    rule.min_bag_score = data.min_bag_score
    rule.updated_by_id = user.id
    db.commit()
    return {
        "campaign_id": campaign_id,
        "min_bag_score": rule.min_bag_score,
        "required_tier": tier_definition(rule.min_bag_score)["name"] if rule.min_bag_score else "STARTER",
        "message": "BagScore gate applies to new enrollments. Existing enrolled users keep access to their active Bag.",
    }
