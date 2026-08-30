import hashlib
import hmac
from collections import defaultdict
from datetime import datetime, UTC, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..admin_user_models import AdminUserAction
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import User, PayoutAddress, WalletConnection, MissionCompletion
from ..risk_models import UserTrustProfile, FraudSignal, DeviceInstallObservation, RiskReview

router = APIRouter(prefix="/api/risk", tags=["risk"])
AUTO_SIGNAL_TYPES = {
    "SHARED_PAYOUT_ADDRESS", "SHARED_VERIFIED_WALLET", "SHARED_DEVICE_INSTALL",
    "MISSION_VELOCITY", "REFERRAL_BURST", "REFERRAL_PAYOUT_OVERLAP",
}


class TrustLevelIn(BaseModel):
    trust_level: str
    note: str = Field(min_length=8, max_length=2000)


class DeviceContextIn(BaseModel):
    install_id: str = Field(min_length=16, max_length=128)


def get_or_create_profile(db: Session, user_id: int):
    profile = db.query(UserTrustProfile).filter(UserTrustProfile.user_id == user_id).first()
    if not profile:
        profile = UserTrustProfile(user_id=user_id)
        db.add(profile)
        db.flush()
    return profile


def install_hash(install_id: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), install_id.encode(), hashlib.sha256).hexdigest()


def risk_band(score: int) -> str:
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "REVIEW"
    return "LOW"


def evaluate_user(db: Session, user: User):
    profile = get_or_create_profile(db, user.id)
    score = 0
    signals: list[tuple[str, str, str]] = []

    addresses = db.query(PayoutAddress).filter(PayoutAddress.user_id == user.id).all()
    for address in addresses:
        shared = db.query(func.count(func.distinct(PayoutAddress.user_id))).filter(
            func.lower(PayoutAddress.address) == address.address.lower(), PayoutAddress.chain == address.chain
        ).scalar() or 0
        if shared > 1:
            score += min(60, int(shared - 1) * 30)
            signals.append(("SHARED_PAYOUT_ADDRESS", "HIGH", f"{address.chain} payout address is also saved by {shared-1} other account(s)."))

    wallets = db.query(WalletConnection).filter(
        WalletConnection.user_id == user.id, WalletConnection.verified_at.isnot(None)
    ).all()
    for wallet in wallets:
        shared = db.query(func.count(func.distinct(WalletConnection.user_id))).filter(
            func.lower(WalletConnection.address) == wallet.address.lower(), WalletConnection.verified_at.isnot(None)
        ).scalar() or 0
        if shared > 1:
            score += min(70, int(shared - 1) * 35)
            signals.append(("SHARED_VERIFIED_WALLET", "HIGH", f"Verified wallet is also attached to {shared-1} other NuBagz account(s)."))

    device_rows = db.query(DeviceInstallObservation).filter(DeviceInstallObservation.user_id == user.id).all()
    for row in device_rows:
        shared = db.query(func.count(func.distinct(DeviceInstallObservation.user_id))).filter(
            DeviceInstallObservation.install_hash == row.install_hash
        ).scalar() or 0
        if shared > 1:
            score += min(60, int(shared - 1) * 30)
            signals.append(("SHARED_DEVICE_INSTALL", "HIGH", f"This NuBagz browser install has been used by {shared-1} other account(s)."))

    recent_cutoff = datetime.now(UTC) - timedelta(minutes=2)
    recent_count = db.query(func.count(MissionCompletion.id)).filter(
        MissionCompletion.user_id == user.id, MissionCompletion.completed_at >= recent_cutoff
    ).scalar() or 0
    if recent_count >= 8:
        score += min(40, (int(recent_count) - 7) * 10)
        signals.append(("MISSION_VELOCITY", "MEDIUM", f"{recent_count} mission completions were recorded in the last two minutes."))

    referral_cutoff = datetime.now(UTC) - timedelta(hours=1)
    referral_burst = db.query(func.count(User.id)).filter(
        User.referred_by_id == user.id, User.created_at >= referral_cutoff
    ).scalar() or 0
    if referral_burst >= 10:
        score += min(40, (int(referral_burst) - 9) * 5)
        signals.append(("REFERRAL_BURST", "MEDIUM", f"{referral_burst} referred accounts were created in the last hour."))

    referred_ids = [row[0] for row in db.query(User.id).filter(User.referred_by_id == user.id).all()]
    cohort_ids = [user.id, *referred_ids]
    if len(cohort_ids) > 1:
        cohort_addresses = db.query(PayoutAddress).filter(PayoutAddress.user_id.in_(cohort_ids)).all()
        grouped: dict[tuple[str, str], set[int]] = defaultdict(set)
        for row in cohort_addresses:
            grouped[(row.chain.lower(), row.address.lower())].add(row.user_id)
        overlaps = [members for members in grouped.values() if len(members) > 1]
        if overlaps:
            largest = max(len(members) for members in overlaps)
            score += min(60, 25 + (largest - 2) * 15)
            signals.append(("REFERRAL_PAYOUT_OVERLAP", "HIGH", f"Referral network contains {len(overlaps)} payout destination(s) shared across multiple accounts."))

    active_keys = {(signal_type, detail) for signal_type, _, detail in signals}
    open_auto = db.query(FraudSignal).filter(
        FraudSignal.user_id == user.id, FraudSignal.status == "OPEN", FraudSignal.signal_type.in_(AUTO_SIGNAL_TYPES)
    ).all()
    for old in open_auto:
        if (old.signal_type, old.detail) not in active_keys:
            old.status = "RESOLVED"
            old.resolved_at = datetime.now(UTC)

    existing_open = {(s.signal_type, s.detail) for s in db.query(FraudSignal).filter(
        FraudSignal.user_id == user.id, FraudSignal.status == "OPEN"
    ).all()}
    for signal_type, severity, detail in signals:
        if (signal_type, detail) not in existing_open:
            db.add(FraudSignal(user_id=user.id, signal_type=signal_type, severity=severity, detail=detail))

    profile.risk_score = min(100, score)
    latest_review = db.query(RiskReview).filter(RiskReview.user_id == user.id).order_by(RiskReview.created_at.desc(), RiskReview.id.desc()).first()
    manual_hold = latest_review and latest_review.trust_level in {"REVIEW", "RESTRICTED"}
    if manual_hold:
        profile.trust_level = latest_review.trust_level
    else:
        if score >= 60:
            profile.trust_level = "REVIEW"
        elif score >= 30 and profile.trust_level != "VERIFIED":
            profile.trust_level = "REVIEW"
        elif score < 30 and profile.trust_level != "VERIFIED":
            profile.trust_level = "NORMAL"
    profile.last_evaluated_at = datetime.now(UTC)
    db.commit()
    return profile


def payload(db: Session, profile: UserTrustProfile):
    signals = db.query(FraudSignal).filter(
        FraudSignal.user_id == profile.user_id, FraudSignal.status == "OPEN"
    ).order_by(FraudSignal.created_at.desc()).all()
    latest_review = db.query(RiskReview).filter(RiskReview.user_id == profile.user_id).order_by(RiskReview.created_at.desc(), RiskReview.id.desc()).first()
    return {
        "user_id": profile.user_id,
        "trust_level": profile.trust_level,
        "risk_score": profile.risk_score,
        "risk_band": risk_band(profile.risk_score),
        "can_earn": profile.trust_level != "RESTRICTED",
        "manual_hold": bool(latest_review and latest_review.trust_level in {"REVIEW", "RESTRICTED"}),
        "last_evaluated_at": profile.last_evaluated_at.isoformat(),
        "signals": [{"id": s.id, "type": s.signal_type, "severity": s.severity, "detail": s.detail} for s in signals],
        "privacy_note": "Device abuse checks use only an HMAC of a random NuBagz-local browser install ID. NuBagz does not create a cross-site device fingerprint.",
    }


@router.post("/context")
def record_context(data: DeviceContextIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    digest = install_hash(data.install_id)
    row = db.query(DeviceInstallObservation).filter(
        DeviceInstallObservation.user_id == user.id, DeviceInstallObservation.install_hash == digest
    ).first()
    if row:
        row.last_seen_at = datetime.now(UTC)
    else:
        db.add(DeviceInstallObservation(user_id=user.id, install_hash=digest))
    db.commit()
    return {"ok": True, "stored": "hashed_install_signal"}


@router.get("/me")
def my_risk(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return payload(db, evaluate_user(db, user))


@router.post("/evaluate")
def evaluate_me(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return payload(db, evaluate_user(db, user))


@router.post("/admin/evaluate-all")
def evaluate_all(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    users = db.query(User).filter(User.is_active.is_(True)).all()
    for user in users:
        evaluate_user(db, user)
    return {"evaluated": len(users)}


@router.get("/users")
def risk_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    profiles = db.query(UserTrustProfile).order_by(UserTrustProfile.risk_score.desc()).all()
    out = []
    for profile in profiles:
        item = payload(db, profile)
        account = db.get(User, profile.user_id)
        review = db.query(RiskReview).filter(RiskReview.user_id == profile.user_id).order_by(RiskReview.created_at.desc(), RiskReview.id.desc()).first()
        item.update({
            "username": account.username if account else f"User #{profile.user_id}",
            "email": account.email if account else None,
            "latest_review": ({"trust_level": review.trust_level, "note": review.note, "created_at": review.created_at.isoformat()} if review else None),
        })
        out.append(item)
    return out


@router.post("/users/{user_id}/trust")
def set_trust(user_id: int, data: TrustLevelIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    level = data.trust_level.upper()
    if level not in {"NORMAL", "VERIFIED", "REVIEW", "RESTRICTED"}:
        raise HTTPException(400, "Invalid trust level")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    profile = get_or_create_profile(db, user_id)
    before = {"trust_level": profile.trust_level, "risk_score": int(profile.risk_score), "account_state": target.account_state}
    profile.trust_level = level
    profile.reviewed_by_id = admin.id
    profile.updated_at = datetime.now(UTC)
    note = data.note.strip()
    db.add(RiskReview(user_id=user_id, reviewed_by_id=admin.id, trust_level=level, note=note))
    db.add(AdminUserAction(
        admin_user_id=admin.id,
        target_user_id=user_id,
        action_type="TRUST_CORRECTED_COMPAT",
        reason=note,
        before_state=before,
        after_state={"trust_level": level, "risk_score": int(profile.risk_score), "account_state": target.account_state},
    ))
    db.commit()
    return payload(db, profile)
