from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Project, Campaign, Enrollment
from ..economy_models import CampaignFunding
from ..engagement_models import WatchBag
from ..economy import campaign_distributed_total

router = APIRouter(prefix="/api/watchbag", tags=["watchbag"])
PUBLIC_PROJECT_STATUSES = {"LIVE", "APPROVED"}


def watchability(campaign: Campaign, db: Session):
    project = db.get(Project, campaign.project_id)
    if campaign.status != "LIVE":
        return False, "Bag is not live", Decimal("0"), None
    if not project or project.status not in PUBLIC_PROJECT_STATUSES:
        return False, "Project is not live", Decimal("0"), None
    funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign.id, CampaignFunding.status == "VERIFIED").first()
    if not funding:
        return False, "Verified reward funding is unavailable", Decimal("0"), None
    distributed = campaign_distributed_total(db, campaign.id)
    remaining = max(Decimal("0"), Decimal(funding.verified_amount) - distributed)
    if remaining < Decimal(campaign.gross_reward_per_user):
        return False, "Verified reward inventory is exhausted", remaining, funding
    enrolled = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == campaign.id).scalar() or 0
    if enrolled >= campaign.max_users:
        return False, "Bag is full", remaining, funding
    return True, "Live, funded and accepting participants", remaining, funding


def public_watchable(campaign: Campaign, db: Session) -> bool:
    return watchability(campaign, db)[0]


def serialize(row: WatchBag, db: Session):
    campaign = db.get(Campaign, row.campaign_id)
    project = db.get(Project, campaign.project_id) if campaign else None
    enrolled = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == campaign.id).scalar() or 0 if campaign else 0
    user_reward = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.user_share_pct) / Decimal("100") if campaign else Decimal("0")
    watchable, reason, remaining, funding = watchability(campaign, db) if campaign else (False, "Bag was removed", Decimal("0"), None)
    return {"id":row.id,"campaign_id":row.campaign_id,"title":campaign.title if campaign else "Unavailable Bag","project_name":project.name if project else None,"symbol":project.symbol if project else None,"category":campaign.category if campaign else None,"reward_asset":campaign.reward_asset if campaign else None,"user_reward":str(user_reward),"status":campaign.status if campaign else "REMOVED","watchable":watchable,"watchability_reason":reason,"verified_funding":str(funding.verified_amount) if funding else None,"remaining_reward_inventory":str(remaining),"spots_left":max(0,campaign.max_users-int(enrolled)) if campaign else 0,"watched_at":row.created_at.isoformat(),"reservation":False}


@router.get("")
def watched_bagz(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(WatchBag).filter(WatchBag.user_id == user.id).order_by(WatchBag.created_at.desc()).all()
    return [serialize(row, db) for row in rows]


@router.get("/status/{campaign_id}")
def watch_status(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Bag not found")
    row = db.query(WatchBag).filter(WatchBag.user_id == user.id, WatchBag.campaign_id == campaign_id).first()
    watchable, reason, remaining, _ = watchability(campaign, db)
    return {"campaign_id":campaign_id,"watched":bool(row),"watchable":watchable,"watchability_reason":reason,"remaining_reward_inventory":str(remaining),"reservation":False}


@router.post("/{campaign_id}")
def watch(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Bag not found")
    watchable, reason, _, _ = watchability(campaign, db)
    if not watchable:
        raise HTTPException(409, f"Only live funded public Bagz can be added to WatchBag: {reason}")
    row = db.query(WatchBag).filter(WatchBag.user_id == user.id, WatchBag.campaign_id == campaign_id).first()
    if not row:
        row = WatchBag(user_id=user.id, campaign_id=campaign_id)
        db.add(row); db.commit(); db.refresh(row)
    return serialize(row, db)


@router.delete("/{campaign_id}")
def unwatch(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(WatchBag).filter(WatchBag.user_id == user.id, WatchBag.campaign_id == campaign_id).first()
    if not row:
        raise HTTPException(404, "Bag is not in your WatchBag")
    db.delete(row); db.commit()
    return {"ok":True,"campaign_id":campaign_id}
