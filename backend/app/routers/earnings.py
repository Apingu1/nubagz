from collections import defaultdict
import csv
from datetime import datetime, UTC
from decimal import Decimal
import io
from fastapi import APIRouter, Depends, HTTPException, Query, Response
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


def historical_price(db: Session, asset: str, at: datetime) -> Decimal | None:
    row = db.query(AssetPriceSnapshot).filter(
        AssetPriceSnapshot.asset_symbol == asset.upper(),
        AssetPriceSnapshot.captured_at <= at,
    ).order_by(AssetPriceSnapshot.captured_at.desc(), AssetPriceSnapshot.id.desc()).first()
    return Decimal(row.price_gbp) if row else None


def estimated_receipt_value(entry: LedgerEntry, db: Session, campaign_cache: dict[int, Campaign | None]):
    amount = Decimal(entry.amount)
    if entry.campaign_id:
        if entry.campaign_id not in campaign_cache:
            campaign_cache[entry.campaign_id] = db.get(Campaign, entry.campaign_id)
        campaign = campaign_cache[entry.campaign_id]
        if campaign and campaign.reward_asset.upper() == entry.asset_symbol.upper() and campaign.estimated_value_gbp is not None and Decimal(campaign.gross_reward_per_user) > 0:
            unit_estimate = Decimal(campaign.estimated_value_gbp) / Decimal(campaign.gross_reward_per_user)
            return amount * unit_estimate, "CAMPAIGN_ESTIMATE", campaign.title
    price = historical_price(db, entry.asset_symbol, entry.created_at)
    if price is not None:
        return amount * price, "PRICE_SNAPSHOT", None
    return None, "UNAVAILABLE", None


def year_bounds(year: int):
    current_year = datetime.now(UTC).year
    if year < 2000 or year > current_year + 1:
        raise HTTPException(400, f"Year must be between 2000 and {current_year + 1}")
    return datetime(year, 1, 1), datetime(year + 1, 1, 1)


def available_years_for_user(db: Session, user_id: int) -> list[int]:
    years = set()
    for created_at, in db.query(LedgerEntry.created_at).filter(LedgerEntry.user_id == user_id).all():
        if created_at:
            years.add(created_at.year)
    for created_at, in db.query(Withdrawal.created_at).filter(Withdrawal.user_id == user_id).all():
        if created_at:
            years.add(created_at.year)
    if not years:
        years.add(datetime.now(UTC).year)
    return sorted(years, reverse=True)


def build_tax_report(db: Session, user: User, year: int):
    start, end = year_bounds(year)
    entries = db.query(LedgerEntry).filter(
        LedgerEntry.user_id == user.id,
        LedgerEntry.created_at >= start,
        LedgerEntry.created_at < end,
    ).order_by(LedgerEntry.created_at.asc(), LedgerEntry.id.asc()).all()
    withdrawals = db.query(Withdrawal).filter(
        Withdrawal.user_id == user.id,
        Withdrawal.created_at >= start,
        Withdrawal.created_at < end,
    ).order_by(Withdrawal.created_at.asc(), Withdrawal.id.asc()).all()

    campaign_cache: dict[int, Campaign | None] = {}
    receipts = []
    receipt_totals = defaultdict(Decimal)
    estimated_receipts_gbp = Decimal("0")
    unpriced_receipts = 0
    for entry in entries:
        asset = entry.asset_symbol.upper()
        amount = Decimal(entry.amount)
        value_gbp, source, campaign_title = estimated_receipt_value(entry, db, campaign_cache)
        receipt_totals[asset] += amount
        if value_gbp is None:
            unpriced_receipts += 1
        else:
            estimated_receipts_gbp += value_gbp
        receipts.append({
            "id": entry.id,
            "received_at": entry.created_at.isoformat(),
            "asset": asset,
            "amount": str(amount),
            "entry_type": entry.entry_type,
            "status": entry.status,
            "campaign_id": entry.campaign_id,
            "campaign_title": campaign_title,
            "note": entry.note,
            "estimated_value_gbp": str(value_gbp.quantize(Decimal("0.01"))) if value_gbp is not None else None,
            "valuation_source": source,
        })

    withdrawal_rows = []
    withdrawn_totals = defaultdict(Decimal)
    estimated_withdrawals_gbp = Decimal("0")
    unpriced_withdrawals = 0
    for wd in withdrawals:
        asset = wd.asset_symbol.upper()
        amount = Decimal(wd.amount)
        price = historical_price(db, asset, wd.created_at)
        value_gbp = amount * price if price is not None else None
        withdrawn_totals[asset] += amount
        if value_gbp is None:
            unpriced_withdrawals += 1
        else:
            estimated_withdrawals_gbp += value_gbp
        withdrawal_rows.append({
            "id": wd.id,
            "requested_at": wd.created_at.isoformat(),
            "asset": asset,
            "amount": str(amount),
            "status": wd.status,
            "chain": wd.chain,
            "wallet_address": wd.wallet_address,
            "tx_hash": wd.tx_hash,
            "estimated_value_gbp": str(value_gbp.quantize(Decimal("0.01"))) if value_gbp is not None else None,
            "valuation_source": "PRICE_SNAPSHOT" if price is not None else "UNAVAILABLE",
        })

    return {
        "year": year,
        "basis": "CALENDAR_YEAR",
        "generated_at": datetime.now(UTC).isoformat(),
        "available_years": available_years_for_user(db, user.id),
        "receipt_count": len(receipts),
        "withdrawal_count": len(withdrawal_rows),
        "estimated_receipts_gbp": str(estimated_receipts_gbp.quantize(Decimal("0.01"))),
        "estimated_withdrawals_gbp": str(estimated_withdrawals_gbp.quantize(Decimal("0.01"))),
        "unpriced_receipt_count": unpriced_receipts,
        "unpriced_withdrawal_count": unpriced_withdrawals,
        "receipts_by_asset": [{"asset": asset, "amount": str(amount)} for asset, amount in sorted(receipt_totals.items())],
        "withdrawals_by_asset": [{"asset": asset, "amount": str(amount)} for asset, amount in sorted(withdrawn_totals.items())],
        "receipts": receipts,
        "withdrawals": withdrawal_rows,
        "disclaimer": "NuBagz provides an estimated activity statement, not tax advice. GBP figures use the campaign estimate recorded for that funded reward or a price snapshot available at/before the event. Missing historical values remain unpriced rather than being back-filled with a later price. Confirm treatment and valuations with your tax adviser or applicable tax authority.",
    }


@router.get("/summary")
def earnings_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    entries = db.query(LedgerEntry).filter(LedgerEntry.user_id == user.id).order_by(LedgerEntry.created_at.asc()).all()
    withdrawals = db.query(Withdrawal).filter(Withdrawal.user_id == user.id).all()

    available = defaultdict(Decimal)
    pending_settlement = defaultdict(Decimal)
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
        elif entry.status == "PENDING_SETTLEMENT":
            pending_settlement[asset] += amount
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
    pending_withdrawal = defaultdict(Decimal)
    for wd in withdrawals:
        asset = wd.asset_symbol.upper()
        if wd.status in {"COMPLETED", "SETTLED"}:
            withdrawn[asset] += Decimal(wd.amount)
        elif wd.status in {"PENDING", "APPROVED"}:
            pending_withdrawal[asset] += Decimal(wd.amount)

    assets = sorted(set(lifetime) | set(withdrawn) | set(pending_withdrawal) | set(pending_settlement))
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
        "pending_settlement": [{"asset": a, "amount": str(pending_settlement[a])} for a in assets if pending_settlement[a]],
        "pending": [{"asset": a, "amount": str(pending_withdrawal[a])} for a in assets if pending_withdrawal[a]],
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


@router.get("/tax-report")
def tax_report(year: int | None = Query(default=None), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    selected_year = year if year is not None else datetime.now(UTC).year
    return build_tax_report(db, user, selected_year)


@router.get("/tax-export.csv")
def tax_export_csv(year: int | None = Query(default=None), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    selected_year = year if year is not None else datetime.now(UTC).year
    report = build_tax_report(db, user, selected_year)
    stream = io.StringIO()
    fields = ["record_type","date","asset","amount","activity","status","estimated_value_gbp","valuation_source","campaign","chain","wallet_address","tx_hash","note"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in report["receipts"]:
        writer.writerow({
            "record_type":"EARNING","date":row["received_at"],"asset":row["asset"],"amount":row["amount"],
            "activity":row["entry_type"],"status":row["status"],"estimated_value_gbp":row["estimated_value_gbp"] or "",
            "valuation_source":row["valuation_source"],"campaign":row["campaign_title"] or "","chain":"","wallet_address":"","tx_hash":"","note":row["note"] or "",
        })
    for row in report["withdrawals"]:
        writer.writerow({
            "record_type":"WITHDRAWAL","date":row["requested_at"],"asset":row["asset"],"amount":row["amount"],
            "activity":"WITHDRAWAL","status":row["status"],"estimated_value_gbp":row["estimated_value_gbp"] or "",
            "valuation_source":row["valuation_source"],"campaign":"","chain":row["chain"],"wallet_address":row["wallet_address"],"tx_hash":row["tx_hash"] or "","note":"",
        })
    filename = f"nubagz-earnings-{selected_year}.csv"
    return Response(content=stream.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition":f'attachment; filename="{filename}"'})
