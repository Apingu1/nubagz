import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ..abuse_models import NetworkObservation, SecurityEvent
from ..admin_user_models import AdminUserAction
from ..challenge_models import Challenge, ChallengeCompletion
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import Enrollment, MissionCompletion, PayoutAddress, User, WalletConnection
from ..risk_models import DeviceInstallObservation, FraudSignal, RiskReview, UserTrustProfile
from ..security_hardening import hash_network_identifier

router = APIRouter(prefix="/api/risk", tags=["risk"])
AUTO_SIGNAL_TYPES = {
    "SHARED_PAYOUT_ADDRESS",
    "SHARED_VERIFIED_WALLET",
    "SHARED_DEVICE_INSTALL",
    "SHARED_NETWORK_SIGNAL",
    "MISSION_VELOCITY",
    "CHALLENGE_VELOCITY",
    "RAPID_SUBMISSION_PATTERN",
    "SUBMISSION_SIMILARITY",
    "API_ABUSE_BURST",
    "REFERRAL_BURST",
    "REFERRAL_PAYOUT_OVERLAP",
    "COMBINED_SYBIL_PATTERN",
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
    # Phase 2.6 moves local-install hashing to the stable anti-abuse key so JWT
    # signing-key rotation does not destroy future device-signal continuity.
    return hash_network_identifier(f"install:{install_id}")


def risk_band(score: int) -> str:
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "REVIEW"
    return "LOW"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _completion_text(completion: ChallengeCompletion) -> str:
    chunks: list[str] = []
    if completion.answer:
        chunks.append(str(completion.answer))

    def collect(value):
        if isinstance(value, str):
            chunks.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(completion.evidence)
    text = " ".join(chunks).lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _append_signal(signals: list[tuple[str, str, str]], signal_type: str, severity: str, detail: str) -> None:
    key = (signal_type, detail)
    if key not in {(existing_type, existing_detail) for existing_type, _, existing_detail in signals}:
        signals.append((signal_type, severity, detail))


def evaluate_user(db: Session, user: User):
    profile = get_or_create_profile(db, user.id)
    score = 0
    signals: list[tuple[str, str, str]] = []
    now = datetime.now(UTC)

    # Reward destinations and verified wallets are strong identity/value signals.
    addresses = db.query(PayoutAddress).filter(PayoutAddress.user_id == user.id).all()
    for address in addresses:
        shared = db.query(func.count(func.distinct(PayoutAddress.user_id))).filter(
            func.lower(PayoutAddress.address) == address.address.lower(),
            PayoutAddress.chain == address.chain,
        ).scalar() or 0
        if shared > 1:
            score += min(60, int(shared - 1) * 30)
            _append_signal(signals, "SHARED_PAYOUT_ADDRESS", "HIGH", f"{address.chain} payout address is also saved by {shared-1} other account(s).")

    wallets = db.query(WalletConnection).filter(
        WalletConnection.user_id == user.id,
        WalletConnection.verified_at.isnot(None),
    ).all()
    for wallet in wallets:
        shared = db.query(func.count(func.distinct(WalletConnection.user_id))).filter(
            func.lower(WalletConnection.address) == wallet.address.lower(),
            WalletConnection.verified_at.isnot(None),
        ).scalar() or 0
        if shared > 1:
            score += min(70, int(shared - 1) * 35)
            _append_signal(signals, "SHARED_VERIFIED_WALLET", "HIGH", f"Verified wallet is also attached to {shared-1} other NuBagz account(s).")

    # A local-install or network observation is supporting evidence only. Neither
    # one can automatically RESTRICT/SUSPEND/DISQUALIFY an account; those states
    # remain separate Admin decisions.
    device_rows = db.query(DeviceInstallObservation).filter(DeviceInstallObservation.user_id == user.id).all()
    for row in device_rows:
        shared = db.query(func.count(func.distinct(DeviceInstallObservation.user_id))).filter(
            DeviceInstallObservation.install_hash == row.install_hash
        ).scalar() or 0
        if shared > 1:
            score += min(45, int(shared - 1) * 22)
            _append_signal(signals, "SHARED_DEVICE_INSTALL", "MEDIUM", f"This NuBagz browser install has been used by {shared-1} other account(s).")

    network_cutoff = now - timedelta(days=7)
    network_hashes = {
        row[0]
        for row in db.query(NetworkObservation.ip_hash).filter(
            NetworkObservation.user_id == user.id,
            NetworkObservation.last_seen_at >= network_cutoff,
        ).all()
    }
    for digest in network_hashes:
        shared = db.query(func.count(func.distinct(NetworkObservation.user_id))).filter(
            NetworkObservation.ip_hash == digest,
            NetworkObservation.last_seen_at >= network_cutoff,
        ).scalar() or 0
        if shared > 1:
            # Keep network evidence deliberately low-weight: households, offices,
            # mobile carriers and VPN exits can legitimately be shared.
            score += min(18, int(shared - 1) * 6)
            _append_signal(signals, "SHARED_NETWORK_SIGNAL", "LOW", f"A recent network signal is shared with {shared-1} other account(s). This is not a standalone enforcement reason.")

    # Burst/behaviour analysis covers both the retired Mission records and the
    # canonical Challenge completion path used by current Bag Work.
    recent_cutoff = now - timedelta(minutes=2)
    legacy_recent = db.query(func.count(MissionCompletion.id)).filter(
        MissionCompletion.user_id == user.id,
        MissionCompletion.completed_at >= recent_cutoff,
    ).scalar() or 0
    if legacy_recent >= 8:
        score += min(40, (int(legacy_recent) - 7) * 10)
        _append_signal(signals, "MISSION_VELOCITY", "MEDIUM", f"{legacy_recent} legacy mission completions were recorded in the last two minutes.")

    challenge_recent = db.query(func.count(ChallengeCompletion.id)).filter(
        ChallengeCompletion.user_id == user.id,
        ChallengeCompletion.submitted_at >= recent_cutoff,
    ).scalar() or 0
    if challenge_recent >= 8:
        score += min(40, (int(challenge_recent) - 7) * 10)
        _append_signal(signals, "CHALLENGE_VELOCITY", "MEDIUM", f"{challenge_recent} Challenge submissions were recorded in the last two minutes.")

    timing_cutoff = now - timedelta(hours=24)
    timing_rows = db.query(ChallengeCompletion, Challenge, Enrollment).join(
        Challenge, Challenge.id == ChallengeCompletion.challenge_id
    ).join(
        Enrollment,
        and_(
            Enrollment.user_id == ChallengeCompletion.user_id,
            Enrollment.campaign_id == Challenge.campaign_id,
        ),
    ).filter(
        ChallengeCompletion.user_id == user.id,
        ChallengeCompletion.submitted_at >= timing_cutoff,
        Challenge.verification_type != "AUTO",
    ).order_by(ChallengeCompletion.submitted_at.desc()).limit(50).all()
    rapid_count = 0
    for completion, _, enrollment in timing_rows:
        submitted_at = _as_utc(completion.submitted_at)
        enrolled_at = _as_utc(enrollment.enrolled_at)
        if submitted_at and enrolled_at:
            seconds = (submitted_at - enrolled_at).total_seconds()
            if 0 <= seconds <= 4:
                rapid_count += 1
    if rapid_count >= 4:
        score += min(35, 15 + (rapid_count - 4) * 5)
        _append_signal(signals, "RAPID_SUBMISSION_PATTERN", "MEDIUM", f"{rapid_count} non-automatic Challenge submissions were made within four seconds of joining their Bag in the last 24 hours.")

    similarity_cutoff = now - timedelta(days=30)
    user_reviewed = db.query(ChallengeCompletion, Challenge).join(
        Challenge, Challenge.id == ChallengeCompletion.challenge_id
    ).filter(
        ChallengeCompletion.user_id == user.id,
        Challenge.verification_type == "PROJECT_REVIEW",
        ChallengeCompletion.submitted_at >= similarity_cutoff,
    ).order_by(ChallengeCompletion.submitted_at.desc()).limit(20).all()
    for completion, challenge in user_reviewed:
        text = _completion_text(completion)
        if len(text) < 80:
            continue
        others = db.query(ChallengeCompletion).filter(
            ChallengeCompletion.challenge_id == challenge.id,
            ChallengeCompletion.user_id != user.id,
            ChallengeCompletion.submitted_at >= similarity_cutoff,
        ).order_by(ChallengeCompletion.submitted_at.desc()).limit(100).all()
        matching_users = {row.user_id for row in others if _completion_text(row) == text}
        if len(matching_users) >= 2:
            shared_total = len(matching_users) + 1
            score += min(35, 20 + (shared_total - 3) * 5)
            _append_signal(signals, "SUBMISSION_SIMILARITY", "MEDIUM", f"A substantial project-reviewed submission is identical across {shared_total} distinct accounts.")
            break

    recent_blocks = db.query(func.count(SecurityEvent.id)).filter(
        SecurityEvent.user_id == user.id,
        SecurityEvent.event_type == "RATE_LIMIT_BLOCK",
        SecurityEvent.created_at >= now - timedelta(minutes=15),
    ).scalar() or 0
    if recent_blocks >= 3:
        score += min(25, 10 + (int(recent_blocks) - 3) * 3)
        _append_signal(signals, "API_ABUSE_BURST", "MEDIUM", f"The account crossed API throttles {recent_blocks} times in the last 15 minutes.")

    referral_cutoff = now - timedelta(hours=1)
    referral_burst = db.query(func.count(User.id)).filter(
        User.referred_by_id == user.id,
        User.created_at >= referral_cutoff,
    ).scalar() or 0
    if referral_burst >= 10:
        score += min(40, (int(referral_burst) - 9) * 5)
        _append_signal(signals, "REFERRAL_BURST", "MEDIUM", f"{referral_burst} referred accounts were created in the last hour.")

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
            _append_signal(signals, "REFERRAL_PAYOUT_OVERLAP", "HIGH", f"Referral network contains {len(overlaps)} payout destination(s) shared across multiple accounts.")

    # Phase 2.6 deliberately gives combinations more meaning than a lone network
    # or browser signal. This raises review priority without changing account state.
    signal_types = {signal_type for signal_type, _, _ in signals}
    families = set()
    if signal_types & {"SHARED_PAYOUT_ADDRESS", "SHARED_VERIFIED_WALLET"}:
        families.add("value_identity")
    if signal_types & {"SHARED_DEVICE_INSTALL", "SHARED_NETWORK_SIGNAL"}:
        families.add("environment")
    if signal_types & {"CHALLENGE_VELOCITY", "RAPID_SUBMISSION_PATTERN", "SUBMISSION_SIMILARITY", "API_ABUSE_BURST", "MISSION_VELOCITY"}:
        families.add("behaviour")
    if signal_types & {"REFERRAL_BURST", "REFERRAL_PAYOUT_OVERLAP"}:
        families.add("referral")
    if len(families) >= 2:
        score += min(25, 8 * len(families))
        _append_signal(signals, "COMBINED_SYBIL_PATTERN", "HIGH", "Multiple independent anti-Sybil signal families overlap on this account. Manual review should consider the evidence together rather than treating one device or network signal as proof.")

    active_keys = {(signal_type, detail) for signal_type, _, detail in signals}
    open_auto = db.query(FraudSignal).filter(
        FraudSignal.user_id == user.id,
        FraudSignal.status == "OPEN",
        FraudSignal.signal_type.in_(AUTO_SIGNAL_TYPES),
    ).all()
    for old in open_auto:
        if (old.signal_type, old.detail) not in active_keys:
            old.status = "RESOLVED"
            old.resolved_at = now

    existing_open = {
        (signal.signal_type, signal.detail)
        for signal in db.query(FraudSignal).filter(
            FraudSignal.user_id == user.id,
            FraudSignal.status == "OPEN",
        ).all()
    }
    for signal_type, severity, detail in signals:
        if (signal_type, detail) not in existing_open:
            db.add(FraudSignal(user_id=user.id, signal_type=signal_type, severity=severity, detail=detail))

    profile.risk_score = min(100, score)
    latest_review = db.query(RiskReview).filter(RiskReview.user_id == user.id).order_by(
        RiskReview.created_at.desc(), RiskReview.id.desc()
    ).first()
    manual_hold = latest_review and latest_review.trust_level in {"REVIEW", "RESTRICTED"}
    if manual_hold:
        profile.trust_level = latest_review.trust_level
    else:
        # Automated analysis can move a user into REVIEW, never into an account
        # restriction or disqualification state. Those remain explicit Admin acts.
        if score >= 60:
            profile.trust_level = "REVIEW"
        elif score >= 30 and profile.trust_level != "VERIFIED":
            profile.trust_level = "REVIEW"
        elif score < 30 and profile.trust_level != "VERIFIED":
            profile.trust_level = "NORMAL"
    profile.last_evaluated_at = now
    db.commit()
    return profile


def payload(db: Session, profile: UserTrustProfile):
    signals = db.query(FraudSignal).filter(
        FraudSignal.user_id == profile.user_id,
        FraudSignal.status == "OPEN",
    ).order_by(FraudSignal.created_at.desc()).all()
    latest_review = db.query(RiskReview).filter(RiskReview.user_id == profile.user_id).order_by(
        RiskReview.created_at.desc(), RiskReview.id.desc()
    ).first()
    return {
        "user_id": profile.user_id,
        "trust_level": profile.trust_level,
        "risk_score": profile.risk_score,
        "risk_band": risk_band(profile.risk_score),
        "can_earn": profile.trust_level != "RESTRICTED",
        "manual_hold": bool(latest_review and latest_review.trust_level in {"REVIEW", "RESTRICTED"}),
        "last_evaluated_at": profile.last_evaluated_at.isoformat(),
        "signals": [{"id": s.id, "type": s.signal_type, "severity": s.severity, "detail": s.detail} for s in signals],
        "privacy_note": "NuBagz anti-abuse checks store keyed hashes of app-local install and network signals, not raw IP addresses or cross-site device fingerprints. A single device or network signal is never an automatic ban.",
    }


@router.post("/context")
def record_context(data: DeviceContextIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    digest = install_hash(data.install_id)
    row = db.query(DeviceInstallObservation).filter(
        DeviceInstallObservation.user_id == user.id,
        DeviceInstallObservation.install_hash == digest,
    ).first()
    if row:
        row.last_seen_at = datetime.now(UTC)
    else:
        db.add(DeviceInstallObservation(user_id=user.id, install_hash=digest))
    db.commit()
    return {"ok": True, "stored": "keyed_install_signal"}


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
        review = db.query(RiskReview).filter(RiskReview.user_id == profile.user_id).order_by(
            RiskReview.created_at.desc(), RiskReview.id.desc()
        ).first()
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
