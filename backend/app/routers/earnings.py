from collections import defaultdict
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, LedgerEntry, Withdrawal

router = APIRouter(prefix="/api/earnings", tags=["earnings"])


@router.get("/summary")
def earnings_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    entries = db.query(LedgerEntry).filter(LedgerEntry.user_id == user.id).order_by(LedgerEntry.created_at.asc()).all()
    withdrawals = db.query(Withdrawal).filter(Withdrawal.user_id == user.id).all()

    available = defaultdict(Decimal)
    lifetime = defaultdict(Decimal)
    referral = defaultdict(Decimal)
    monthly = defaultdict(lambda: defaultdict(Decimal))
    for entry in entries:
        amount = Decimal(entry.amount)
        lifetime[entry.asset_symbol] += amount
        if entry.status == "AVAILABLE":
            available[entry.asset_symbol] += amount
        if entry.entry_type == "REFERRAL_SHARE":
            referral[entry.asset_symbol] += amount
        month = entry.created_at.strftime("%Y-%m")
        monthly[month][entry.asset_symbol] += amount

    withdrawn = defaultdict(Decimal)
    pending = defaultdict(Decimal)
    for wd in withdrawals:
        if wd.status in {"COMPLETED", "SETTLED"}:
            withdrawn[wd.asset_symbol] += Decimal(wd.amount)
        elif wd.status in {"PENDING", "APPROVED"}:
            pending[wd.asset_symbol] += Decimal(wd.amount)

    assets = sorted(set(lifetime) | set(withdrawn) | set(pending))
    return {
        "lifetime": [{"asset": a, "amount": str(lifetime[a])} for a in assets],
        "available": [{"asset": a, "amount": str(available[a])} for a in assets if available[a]],
        "pending": [{"asset": a, "amount": str(pending[a])} for a in assets if pending[a]],
        "withdrawn": [{"asset": a, "amount": str(withdrawn[a])} for a in assets if withdrawn[a]],
        "referral": [{"asset": a, "amount": str(referral[a])} for a in assets if referral[a]],
        "unique_assets": len([a for a in assets if lifetime[a] > 0]),
        "monthly": [
            {"month": month, "assets": [{"asset": asset, "amount": str(amount)} for asset, amount in sorted(values.items())]}
            for month, values in sorted(monthly.items())
        ],
    }
