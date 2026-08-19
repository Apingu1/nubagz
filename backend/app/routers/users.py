from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, LedgerEntry, Enrollment, Withdrawal
from ..schemas import DashboardOut, RewardBalance, WithdrawalIn

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    balances_q = db.query(LedgerEntry.asset_symbol, func.sum(LedgerEntry.amount)).filter(LedgerEntry.user_id == user.id, LedgerEntry.status == "AVAILABLE").group_by(LedgerEntry.asset_symbol).all()
    balances = [RewardBalance(asset_symbol=s, amount=a or 0) for s, a in balances_q]
    active = db.query(func.count(Enrollment.id)).filter(Enrollment.user_id == user.id, Enrollment.status == "ACTIVE").scalar() or 0
    completed = db.query(func.count(Enrollment.id)).filter(Enrollment.user_id == user.id, Enrollment.status == "COMPLETED").scalar() or 0
    recent = db.query(LedgerEntry).filter(LedgerEntry.user_id == user.id).order_by(LedgerEntry.created_at.desc()).limit(8).all()
    return DashboardOut(
        lifetime_assets=len(balances), active_bagz=active, completed_bagz=completed, xp=user.xp,
        bag_score=user.bag_score, streak_days=user.streak_days, balances=balances,
        recent_activity=[{"asset": r.asset_symbol, "amount": str(r.amount), "type": r.entry_type, "note": r.note, "created_at": r.created_at.isoformat()} for r in recent]
    )


@router.get("/leaderboard")
def leaderboard(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.is_active == True).order_by(User.bag_score.desc(), User.xp.desc()).limit(50).all()
    return [{"rank": i + 1, "username": u.username, "bag_score": u.bag_score, "xp": u.xp, "streak_days": u.streak_days} for i, u in enumerate(users)]


@router.post("/withdrawals")
def request_withdrawal(data: WithdrawalIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    available = db.query(func.coalesce(func.sum(LedgerEntry.amount), 0)).filter(LedgerEntry.user_id == user.id, LedgerEntry.asset_symbol == data.asset_symbol, LedgerEntry.status == "AVAILABLE").scalar() or Decimal("0")
    reserved = db.query(func.coalesce(func.sum(Withdrawal.amount), 0)).filter(Withdrawal.user_id == user.id, Withdrawal.asset_symbol == data.asset_symbol, Withdrawal.status.in_(["PENDING", "APPROVED"])).scalar() or Decimal("0")
    if Decimal(available) - Decimal(reserved) < data.amount:
        raise HTTPException(400, "Insufficient available balance")
    wd = Withdrawal(user_id=user.id, **data.model_dump())
    db.add(wd)
    db.commit()
    db.refresh(wd)
    return {"id": wd.id, "status": wd.status, "asset_symbol": wd.asset_symbol, "amount": str(wd.amount)}
