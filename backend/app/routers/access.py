from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Campaign, Project
from ..economy_models import CampaignAccessRule

router = APIRouter(prefix="/api/access", tags=["access"])


class AccessRuleIn(BaseModel):
    min_bag_score: int = Field(ge=0, le=1000)


def tier(score: int):
    if score >= 800: return "ELITE", None
    if score >= 600: return "PREMIUM", 800
    if score >= 400: return "CONTRIBUTOR", 600
    if score >= 200: return "EXPLORER", 400
    return "STARTER", 200


@router.get("/me")
def my_access(user: User = Depends(get_current_user)):
    name, next_score = tier(user.bag_score)
    return {"bag_score": user.bag_score, "tier": name, "next_tier_score": next_score, "points_to_next": max(0, next_score - user.bag_score) if next_score else 0}


@router.get("/campaigns/{campaign_id}")
def campaign_access(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    rule = db.query(CampaignAccessRule).filter(CampaignAccessRule.campaign_id == campaign_id).first()
    minimum = rule.min_bag_score if rule else 0
    return {"campaign_id": campaign_id, "min_bag_score": minimum, "eligible": user.bag_score >= minimum, "your_bag_score": user.bag_score}


@router.post("/campaigns/{campaign_id}")
def set_campaign_access(campaign_id: int, data: AccessRuleIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, campaign_id)
    project = db.get(Project, campaign.project_id) if campaign else None
    if not campaign or not project or project.owner_id != user.id:
        raise HTTPException(403, "You do not manage this campaign")
    rule = db.query(CampaignAccessRule).filter(CampaignAccessRule.campaign_id == campaign_id).first()
    if not rule:
        rule = CampaignAccessRule(campaign_id=campaign_id, updated_by_id=user.id)
        db.add(rule)
    rule.min_bag_score = data.min_bag_score
    rule.updated_by_id = user.id
    db.commit()
    return {"campaign_id": campaign_id, "min_bag_score": rule.min_bag_score}
