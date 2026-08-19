from datetime import datetime, UTC, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import User, PayoutAddress, WalletConnection, MissionCompletion
from ..risk_models import UserTrustProfile, FraudSignal

router = APIRouter(prefix="/api/risk", tags=["risk"])
AUTO_SIGNAL_TYPES = {"SHARED_PAYOUT_ADDRESS", "SHARED_VERIFIED_WALLET", "MISSION_VELOCITY", "REFERRAL_BURST"}


class TrustLevelIn(BaseModel):
    trust_level: str


def get_or_create_profile(db: Session, user_id: int):
    profile = db.query(UserTrustProfile).filter(UserTrustProfile.user_id == user_id).first()
    if not profile:
        profile = UserTrustProfile(user_id=user_id)
        db.add(profile)
        db.flush()
    return profile


def evaluate_user(db: Session, user: User):
    profile = get_or_create_profile(db, user.id)
    score = 0
    signals: list[tuple[str, str, str]] = []

    addresses = db.query(PayoutAddress).filter(PayoutAddress.user_id == user.id).all()
    for address in addresses:
        shared = db.query(func.count(func.distinct(PayoutAddress.user_id))).filter(func.lower(PayoutAddress.address) == address.address.lower(), PayoutAddress.chain == address.chain).scalar() or 0
        if shared > 1:
            score += min(60, int(shared - 1) * 30)
            signals.append(("SHARED_PAYOUT_ADDRESS", "HIGH", f"{address.chain} payout address is also saved by {shared-1} other account(s)."))

    wallets = db.query(WalletConnection).filter(WalletConnection.user_id == user.id, WalletConnection.verified_at.isnot(None)).all()
    for wallet in wallets:
        shared = db.query(func.count(func.distinct(WalletConnection.user_id))).filter(func.lower(WalletConnection.address) == wallet.address.lower(), WalletConnection.verified_at.isnot(None)).scalar() or 0
        if shared > 1:
            score += min(70, int(shared - 1) * 35)
            signals.append(("SHARED_VERIFIED_WALLET", "HIGH", f"Verified wallet is also attached to {shared-1} other NuBagz account(s)."))

    recent_cutoff = datetime.now(UTC) - timedelta(minutes=2)
    recent_count = db.query(func.count(MissionCompletion.id)).filter(MissionCompletion.user_id == user.id, MissionCompletion.completed_at >= recent_cutoff).scalar() or 0
    if recent_count >= 8:
        score += min(40, (int(recent_count) - 7) * 10)
        signals.append(("MISSION_VELOCITY", "MEDIUM", f"{recent_count} mission completions recorded in the last two minutes."))

    referral_cutoff = datetime.now(UTC) - timedelta(hours=1)
    referral_burst = db.query(func.count(User.id)).filter(User.referred_by_id == user.id, User.created_at >= referral_cutoff).scalar() or 0
    if referral_burst >= 10:
        score += min(40, (int(referral_burst) - 9) * 5)
        signals.append(("REFERRAL_BURST", "MEDIUM", f"{referral_burst} referred accounts were created in the last hour."))

    active_keys = {(signal_type, detail) for signal_type, _, detail in signals}
    open_auto = db.query(FraudSignal).filter(FraudSignal.user_id == user.id, FraudSignal.status == "OPEN", FraudSignal.signal_type.in_(AUTO_SIGNAL_TYPES)).all()
    for old in open_auto:
        if (old.signal_type, old.detail) not in active_keys:
            old.status = "RESOLVED"
            old.resolved_at = datetime.now(UTC)
    existing_open = {(s.signal_type, s.detail) for s in db.query(FraudSignal).filter(FraudSignal.user_id == user.id, FraudSignal.status == "OPEN").all()}
    for signal_type, severity, detail in signals:
        if (signal_type, detail) not in existing_open:
            db.add(FraudSignal(user_id=user.id, signal_type=signal_type, severity=severity, detail=detail))

    profile.risk_score = min(100, score)
    if profile.trust_level != "RESTRICTED":
        if score >= 30:
            profile.trust_level = "REVIEW"
        elif profile.trust_level != "VERIFIED":
            profile.trust_level = "NORMAL"
    profile.last_evaluated_at = datetime.now(UTC)
    db.commit()
    return profile


def payload(db: Session, profile: UserTrustProfile):
    signals = db.query(FraudSignal).filter(FraudSignal.user_id == profile.user_id, FraudSignal.status == "OPEN").order_by(FraudSignal.created_at.desc()).all()
    return {"user_id": profile.user_id, "trust_level": profile.trust_level, "risk_score": profile.risk_score, "last_evaluated_at": profile.last_evaluated_at.isoformat(), "signals": [{"id":s.id,"type":s.signal_type,"severity":s.severity,"detail":s.detail} for s in signals]}


@router.get("/me")
def my_risk(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return payload(db, evaluate_user(db, user))


@router.post("/evaluate")
def evaluate_me(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return payload(db, evaluate_user(db, user))


@router.get("/users")
def risk_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    profiles = db.query(UserTrustProfile).order_by(UserTrustProfile.risk_score.desc()).all()
    return [payload(db,p) for p in profiles]


@router.post("/users/{user_id}/trust")
def set_trust(user_id:int, data:TrustLevelIn, db:Session=Depends(get_db), admin:User=Depends(require_admin)):
    level=data.trust_level.upper()
    if level not in {"NORMAL","VERIFIED","REVIEW","RESTRICTED"}: raise HTTPException(400,"Invalid trust level")
    if not db.get(User,user_id): raise HTTPException(404,"User not found")
    profile=get_or_create_profile(db,user_id);profile.trust_level=level;profile.reviewed_by_id=admin.id;profile.updated_at=datetime.now(UTC);db.commit()
    return payload(db,profile)
