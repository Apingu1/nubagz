from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Campaign, Enrollment
from ..economy_models import BagDrop, BagDropItem, BagDropClaim, AssetPriceSnapshot, CampaignFunding, CampaignAccessRule
from ..risk_models import UserTrustProfile
from ..economy import campaign_distributed_total

router = APIRouter(prefix="/api/daily", tags=["daily-earn"])


def price_map(db: Session):
    rows = db.query(AssetPriceSnapshot).order_by(AssetPriceSnapshot.asset_symbol.asc(), AssetPriceSnapshot.captured_at.desc(), AssetPriceSnapshot.id.desc()).all()
    out = {}
    for row in rows:
        symbol = row.asset_symbol.upper()
        if symbol not in out:
            out[symbol] = Decimal(row.price_gbp)
    return out


def campaign_is_eligible(db: Session, user: User, campaign: Campaign) -> bool:
    access = db.query(CampaignAccessRule).filter(CampaignAccessRule.campaign_id == campaign.id).first()
    if access and user.bag_score < access.min_bag_score:
        return False
    funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign.id, CampaignFunding.status == "VERIFIED").first()
    if not funding:
        return False
    distributed = campaign_distributed_total(db, campaign.id)
    return Decimal(funding.verified_amount) - distributed >= Decimal(campaign.gross_reward_per_user)


@router.get("/earn")
def daily_earn(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trust = db.query(UserTrustProfile).filter(UserTrustProfile.user_id == user.id).first()
    if trust and trust.trust_level == "RESTRICTED":
        return {"estimated_available_gbp": "0", "opportunity_count": 0, "campaign_count": 0, "bagdrop_count": 0, "opportunities": [], "restricted": True}

    completed_campaigns = {row[0] for row in db.query(Enrollment.campaign_id).filter(Enrollment.user_id == user.id, Enrollment.status == "COMPLETED").all()}
    campaigns = db.query(Campaign).filter(Campaign.status == "LIVE").order_by(Campaign.featured.desc(), Campaign.created_at.desc()).all()
    campaign_items = []
    total_gbp = Decimal("0")
    for campaign in campaigns:
        if campaign.id in completed_campaigns or not campaign_is_eligible(db, user, campaign):
            continue
        estimated_user_gbp = None
        if campaign.estimated_value_gbp is not None:
            estimated_user_gbp = Decimal(campaign.estimated_value_gbp) * Decimal(campaign.user_share_pct) / Decimal("100")
            total_gbp += estimated_user_gbp
        campaign_items.append({
            "type": "CAMPAIGN",
            "id": campaign.id,
            "title": campaign.title,
            "category": campaign.category,
            "reward": f"{Decimal(campaign.gross_reward_per_user) * Decimal(campaign.user_share_pct) / Decimal('100')} {campaign.reward_asset}",
            "estimated_value_gbp": str(estimated_user_gbp) if estimated_user_gbp is not None else None,
            "featured": campaign.featured,
        })

    prices = price_map(db)
    claimed_drop_ids = {row[0] for row in db.query(BagDropClaim.drop_id).filter(BagDropClaim.user_id == user.id).all()}
    drops = db.query(BagDrop).filter(BagDrop.status == "LIVE", BagDrop.funding_status == "VERIFIED").order_by(BagDrop.created_at.desc()).all()
    drop_items = []
    for drop in drops:
        if drop.id in claimed_drop_ids or drop.claims_count >= drop.max_claims or user.bag_score < drop.min_bag_score:
            continue
        items = db.query(BagDropItem).filter(BagDropItem.drop_id == drop.id).all()
        value = Decimal("0")
        all_priced = bool(items)
        rewards = []
        for item in items:
            rewards.append(f"{item.amount_per_claim} {item.asset_symbol}")
            price = prices.get(item.asset_symbol.upper())
            if price is None:
                all_priced = False
            else:
                value += Decimal(item.amount_per_claim) * price
        if all_priced:
            total_gbp += value
        drop_items.append({
            "type": "BAGDROP",
            "id": drop.id,
            "title": drop.title,
            "category": drop.rarity,
            "reward": " + ".join(rewards),
            "estimated_value_gbp": str(value) if all_priced else None,
            "featured": drop.rarity in {"EPIC", "LEGENDARY"},
        })

    opportunities = sorted(campaign_items + drop_items, key=lambda item: (not item["featured"], -(Decimal(item["estimated_value_gbp"]) if item["estimated_value_gbp"] else Decimal("0"))))
    return {
        "estimated_available_gbp": str(total_gbp),
        "opportunity_count": len(opportunities),
        "campaign_count": len(campaign_items),
        "bagdrop_count": len(drop_items),
        "opportunities": opportunities[:20],
        "restricted": False,
    }
