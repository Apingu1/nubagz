from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Project, Campaign, Enrollment, LedgerEntry
from ..economy_models import CampaignFunding
from ..engagement_models import WatchBag

router = APIRouter(prefix="/api/watchbag", tags=["watchbag"])


def public_watchable(campaign: Campaign, db: Session) -> bool:
    if campaign.status != "LIVE":
        return False
    project = db.get(Project, campaign.project_id)
    if not project or project.status != "APPROVED":
        return False
    funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign.id, CampaignFunding.status == "VERIFIED").first()
    if not funding:
        return False
    distributed = db.query(func.coalesce(func.sum(LedgerEntry.amount), 0)).filter(LedgerEntry.campaign_id == campaign.id).scalar() or Decimal("0")
    return Decimal(funding.verified_amount) - Decimal(distributed) >= Decimal(campaign.gross_reward_per_user)


def serialize(row: WatchBag, db: Session):
    campaign = db.get(Campaign, row.campaign_id)
    project = db.get(Project, campaign.project_id) if campaign else None
    enrolled = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == campaign.id).scalar() or 0 if campaign else 0
    user_reward = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.user_share_pct) / Decimal("100") if campaign else Decimal("0")
    return {
        "id":row.id,"campaign_id":row.campaign_id,"title":campaign.title if campaign else "Unavailable Bag",
        "project_name":project.name if project else None,"symbol":project.symbol if project else None,"category":campaign.category if campaign else None,
        "reward_asset":campaign.reward_asset if campaign else None,"user_reward":str(user_reward),
        "status":campaign.status if campaign else "REMOVED","watchable":public_watchable(campaign,db) if campaign else False,
        "spots_left":max(0,campaign.max_users-int(enrolled)) if campaign else 0,"watched_at":row.created_at.isoformat(),
    }


@router.get("")
def watched_bagz(db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    rows=db.query(WatchBag).filter(WatchBag.user_id==user.id).order_by(WatchBag.created_at.desc()).all()
    return [serialize(row,db) for row in rows]


@router.get("/status/{campaign_id}")
def watch_status(campaign_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    campaign=db.get(Campaign,campaign_id)
    if not campaign: raise HTTPException(404,"Bag not found")
    row=db.query(WatchBag).filter(WatchBag.user_id==user.id,WatchBag.campaign_id==campaign_id).first()
    return {"campaign_id":campaign_id,"watched":bool(row),"watchable":public_watchable(campaign,db)}


@router.post("/{campaign_id}")
def watch(campaign_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    campaign=db.get(Campaign,campaign_id)
    if not campaign or not public_watchable(campaign,db): raise HTTPException(409,"Only live funded public Bagz can be added to WatchBag")
    row=db.query(WatchBag).filter(WatchBag.user_id==user.id,WatchBag.campaign_id==campaign_id).first()
    if not row:
        row=WatchBag(user_id=user.id,campaign_id=campaign_id);db.add(row);db.commit();db.refresh(row)
    return serialize(row,db)


@router.delete("/{campaign_id}")
def unwatch(campaign_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    row=db.query(WatchBag).filter(WatchBag.user_id==user.id,WatchBag.campaign_id==campaign_id).first()
    if not row: raise HTTPException(404,"Bag is not in your WatchBag")
    db.delete(row);db.commit();return {"ok":True,"campaign_id":campaign_id}
