from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Campaign, Enrollment
from ..economy_models import BagDrop, BagDropItem, BagDropClaim, AssetPriceSnapshot

router = APIRouter(prefix="/api/daily", tags=["daily-earn"])


def price_map(db: Session):
    rows = db.query(AssetPriceSnapshot).order_by(AssetPriceSnapshot.asset_symbol.asc(), AssetPriceSnapshot.captured_at.desc(), AssetPriceSnapshot.id.desc()).all()
    out = {}
    for row in rows:
        symbol = row.asset_symbol.upper()
        if symbol not in out:
            out[symbol] = Decimal(row.price_gbp)
    return out


@router.get("/earn")
def daily_earn(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    completed_campaigns = {row[0] for row in db.query(Enrollment.campaign_id).filter(Enrollment.user_id == user.id, Enrollment.status == "COMPLETED").all()}
    campaigns = db.query(Campaign).filter(Campaign.status == "LIVE").order_by(Campaign.featured.desc(), Campaign.created_at.desc()).all()
    campaign_items = []
    total_gbp = Decimal("0")
    for campaign in campaigns:
        if campaign.id in completed_campaigns:
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
    drops = db.query(BagDrop).filter(BagDrop.status == "LIVE").order_by(BagDrop.created_at.desc()).all()
    drop_items = []
    for drop in drops:
        if drop.id in claimed_drop_ids or drop.claims_count >= drop.max_claims or user.bag_score < drop.min_bag_score:
            continue
        items = db.query(BagDropItem).filter(BagDropItem.drop_id == drop.id).all()
        value = Decimal("0")
        has_price = False
        rewards = []
        for item in items:
            rewards.append(f"{item.amount_per_claim} {item.asset_symbol}")
            if item.asset_symbol.upper() in prices:
                has_price = True
                value += Decimal(item.amount_per_claim) * prices[item.asset_symbol.upper()]
        if has_price:
            total_gbp += value
        drop_items.append({
            "type": "BAGDROP",
            "id": drop.id,
            "title": drop.title,
            "category": drop.rarity,
            "reward": " + ".join(rewards),
            "estimated_value_gbp": str(value) if has_price else None,
            "featured": drop.rarity in {"EPIC", "LEGENDARY"},
        })

    opportunities = sorted(campaign_items + drop_items, key=lambda item: (not item["featured"], -(Decimal(item["estimated_value_gbp"]) if item["estimated_value_gbp"] else Decimal("0"))))
    return {
        "estimated_available_gbp": str(total_gbp),
        "opportunity_count": len(opportunities),
        "campaign_count": len(campaign_items),
        "bagdrop_count": len(drop_items),
        "opportunities": opportunities[:20],
    }
