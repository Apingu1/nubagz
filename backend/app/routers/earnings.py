from collections import defaultdict
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, LedgerEntry, Withdrawal, Campaign
from ..economy_models import AssetPriceSnapshot

router = APIRouter(prefix="/api/earnings", tags=["earnings"])


def latest_prices(db: Session) -> dict[str, Decimal]:
    rows = db.query(AssetPriceSnapshot).order_by(AssetPriceSnapshot.asset_symbol.asc(), AssetPriceSnapshot.captured_at.desc(), AssetPriceSnapshot.id.desc()).all()
    prices: dict[str, Decimal] = {}
    for row in rows:
        symbol = row.asset_symbol.upper()
        if symbol not in prices:
            prices[symbol] = Decimal(row.price_gbp)
    return prices


@router.get("/summary")
def earnings_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    entries = db.query(LedgerEntry).filter(LedgerEntry.user_id == user.id).order_by(LedgerEntry.created_at.asc()).all()
    withdrawals = db.query(Withdrawal).filter(Withdrawal.user_id == user.id).all()

    available = defaultdict(Decimal)
    lifetime = defaultdict(Decimal)
    referral = defaultdict(Decimal)
    monthly = defaultdict(lambda: defaultdict(Decimal))
    original_value = defaultdict(Decimal)
    campaign_cache: dict[int, Campaign | None] = {}

    for entry in entries:
        asset = entry.asset_symbol.upper()
        amount = Decimal(entry.amount)
        lifetime[asset] += amount
        if entry.status == "AVAILABLE":
            available[asset] += amount
        if entry.entry_type == "REFERRAL_SHARE":
            referral[asset] += amount
        month = entry.created_at.strftime("%Y-%m")
        monthly[month][asset] += amount
        if entry.campaign_id:
            if entry.campaign_id not in campaign_cache:
                campaign_cache[entry.campaign_id] = db.get(Campaign, entry.campaign_id)
            campaign = campaign_cache[entry.campaign_id]
            if campaign and campaign.estimated_value_gbp:
                gross_value = Decimal(campaign.estimated_value_gbp)
                if entry.entry_type == "CAMPAIGN_REWARD":
                    original_value[asset] += gross_value * Decimal(campaign.user_share_pct) / Decimal("100")
                elif entry.entry_type == "REFERRAL_SHARE":
                    original_value[asset] += gross_value * Decimal(campaign.referral_share_pct) / Decimal("100")

    withdrawn = defaultdict(Decimal)
    pending = defaultdict(Decimal)
    for wd in withdrawals:
        asset = wd.asset_symbol.upper()
        if wd.status in {"COMPLETED", "SETTLED"}:
            withdrawn[asset] += Decimal(wd.amount)
        elif wd.status in {"PENDING", "APPROVED"}:
            pending[asset] += Decimal(wd.amount)

    assets = sorted(set(lifetime) | set(withdrawn) | set(pending))
    prices = latest_prices(db)
    valuations = []
    for asset in assets:
        current_price = prices.get(asset)
        current_value = available[asset] * current_price if current_price is not None else None
        original = original_value[asset]
        change_pct = None
        if current_value is not None and original > 0:
            change_pct = ((current_value - original) / original) * Decimal("100")
        valuations.append({
            "asset": asset,
            "available_amount": str(available[asset]),
            "current_price_gbp": str(current_price) if current_price is not None else None,
            "current_value_gbp": str(current_value) if current_value is not None else None,
            "original_estimated_value_gbp": str(original) if original > 0 else None,
            "change_pct": str(change_pct) if change_pct is not None else None,
        })

    total_current_value = sum((Decimal(v["current_value_gbp"]) for v in valuations if v["current_value_gbp"] is not None), Decimal("0"))
    total_original_value = sum((Decimal(v["original_estimated_value_gbp"]) for v in valuations if v["original_estimated_value_gbp"] is not None), Decimal("0"))

    return {
        "lifetime": [{"asset": a, "amount": str(lifetime[a])} for a in assets],
        "available": [{"asset": a, "amount": str(available[a])} for a in assets if available[a]],
        "pending": [{"asset": a, "amount": str(pending[a])} for a in assets if pending[a]],
        "withdrawn": [{"asset": a, "amount": str(withdrawn[a])} for a in assets if withdrawn[a]],
        "referral": [{"asset": a, "amount": str(referral[a])} for a in assets if referral[a]],
        "unique_assets": len([a for a in assets if lifetime[a] > 0]),
        "total_current_value_gbp": str(total_current_value),
        "total_original_estimated_value_gbp": str(total_original_value),
        "valuations": valuations,
        "monthly": [
            {"month": month, "assets": [{"asset": asset, "amount": str(amount)} for asset, amount in sorted(values.items())]}
            for month, values in sorted(monthly.items())
        ],
    }
