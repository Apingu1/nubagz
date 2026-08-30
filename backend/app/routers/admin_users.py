from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..admin_user_models import AdminUserAction, UserRewardHold
from ..challenge_models import ChallengeCompletion, SocialAccount
from ..db import get_db
from ..deps import require_admin
from ..models import ACCOUNT_STATES, LedgerEntry, PayoutAddress, User, UserSession, WalletConnection, Withdrawal
from ..risk_models import FraudSignal, RiskReview, UserTrustProfile
from ..security_models import PrivyIdentityBinding

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])
TRUST_LEVELS = {"NORMAL", "VERIFIED", "REVIEW", "RESTRICTED"}
SIGNAL_STATES = {"OPEN", "RESOLVED"}


class ReasonIn(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class AccountStateIn(ReasonIn):
    account_state: str


class SessionRevokeIn(ReasonIn):
    session_id: str | None = Field(default=None, max_length=64)


class TrustCorrectionIn(ReasonIn):
    trust_level: str


class SignalDecisionIn(ReasonIn):
    status: str


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _risk_band(score: int) -> str:
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "REVIEW"
    return "LOW"


def _active_reward_hold(db: Session, user_id: int) -> UserRewardHold | None:
    return db.query(UserRewardHold).filter(
        UserRewardHold.user_id == user_id,
        UserRewardHold.status == "ACTIVE",
    ).order_by(UserRewardHold.created_at.desc(), UserRewardHold.id.desc()).first()


def _record_action(
    db: Session,
    admin: User,
    target: User,
    action_type: str,
    reason: str,
    before_state: dict | None = None,
    after_state: dict | None = None,
) -> None:
    db.add(AdminUserAction(
        admin_user_id=admin.id,
        target_user_id=target.id,
        action_type=action_type,
        reason=reason.strip(),
        before_state=before_state,
        after_state=after_state,
    ))


def _revoke_sessions(db: Session, user_id: int, reason: str, session_id: str | None = None) -> int:
    query = db.query(UserSession).filter(
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
    )
    if session_id:
        query = query.filter(UserSession.session_id == session_id)
    rows = query.all()
    now = _now()
    for row in rows:
        row.revoked_at = now
        row.revoke_reason = reason[:255]
    return len(rows)


def _trust_summary(db: Session, user_id: int) -> dict:
    profile = db.query(UserTrustProfile).filter(UserTrustProfile.user_id == user_id).first()
    open_signals = db.query(func.count(FraudSignal.id)).filter(
        FraudSignal.user_id == user_id,
        FraudSignal.status == "OPEN",
    ).scalar() or 0
    return {
        "trust_level": profile.trust_level if profile else "NORMAL",
        "risk_score": int(profile.risk_score) if profile else 0,
        "risk_band": _risk_band(int(profile.risk_score) if profile else 0),
        "open_signal_count": int(open_signals),
        "last_evaluated_at": profile.last_evaluated_at.isoformat() if profile and profile.last_evaluated_at else None,
    }


def _user_summary(db: Session, user: User) -> dict:
    now = _now()
    active_sessions = db.query(func.count(UserSession.id)).filter(
        UserSession.user_id == user.id,
        UserSession.revoked_at.is_(None),
        UserSession.expires_at > now.replace(tzinfo=None),
    ).scalar() or 0
    signer = db.query(WalletConnection).filter(
        WalletConnection.user_id == user.id,
        WalletConnection.is_primary_interactive.is_(True),
        WalletConnection.verified_at.isnot(None),
    ).first()
    hold = _active_reward_hold(db, user.id)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "account_state": user.account_state,
        "created_at": user.created_at.isoformat(),
        "last_active_at": user.last_active_at.isoformat() if user.last_active_at else None,
        "trust": _trust_summary(db, user.id),
        "security": {"active_session_count": int(active_sessions)},
        "wallet": {
            "interactive_signer": signer.address if signer else None,
            "reward_destination": user.wallet_address,
        },
        "reward_hold": {
            "active": bool(hold),
            "hold_id": hold.id if hold else None,
            "created_at": hold.created_at.isoformat() if hold else None,
        },
    }


def _require_target(db: Session, user_id: int, lock: bool = False) -> User:
    query = db.query(User).filter(User.id == user_id)
    if lock:
        query = query.with_for_update()
    target = query.first()
    if not target:
        raise HTTPException(404, "User not found")
    return target


@router.get("")
def list_users(
    q: str | None = Query(default=None, max_length=255),
    account_state: str | None = Query(default=None),
    trust_level: str | None = Query(default=None),
    reward_hold: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = db.query(User)

    if account_state:
        state = account_state.upper()
        if state not in ACCOUNT_STATES:
            raise HTTPException(400, "Invalid account state")
        query = query.filter(User.account_state == state)

    if trust_level:
        level = trust_level.upper()
        if level not in TRUST_LEVELS:
            raise HTTPException(400, "Invalid trust level")
        trust_ids = db.query(UserTrustProfile.user_id).filter(UserTrustProfile.trust_level == level)
        if level == "NORMAL":
            known_ids = db.query(UserTrustProfile.user_id)
            query = query.filter(or_(User.id.in_(trust_ids), ~User.id.in_(known_ids)))
        else:
            query = query.filter(User.id.in_(trust_ids))

    if reward_hold is not None:
        held_ids = db.query(UserRewardHold.user_id).filter(UserRewardHold.status == "ACTIVE")
        query = query.filter(User.id.in_(held_ids) if reward_hold else ~User.id.in_(held_ids))

    term = (q or "").strip()
    if term:
        pattern = f"%{term.lower()}%"
        wallet_ids = db.query(WalletConnection.user_id).filter(func.lower(WalletConnection.address).like(pattern))
        payout_ids = db.query(PayoutAddress.user_id).filter(func.lower(PayoutAddress.address).like(pattern))
        social_ids = db.query(SocialAccount.user_id).filter(or_(
            func.lower(SocialAccount.provider_user_id).like(pattern),
            func.lower(func.coalesce(SocialAccount.username, "")).like(pattern),
            func.lower(func.coalesce(SocialAccount.email, "")).like(pattern),
        ))
        privy_ids = db.query(PrivyIdentityBinding.user_id).filter(func.lower(PrivyIdentityBinding.privy_user_id).like(pattern))
        clauses = [
            func.lower(User.username).like(pattern),
            func.lower(User.email).like(pattern),
            func.lower(func.coalesce(User.wallet_address, "")).like(pattern),
            User.id.in_(wallet_ids),
            User.id.in_(payout_ids),
            User.id.in_(social_ids),
            User.id.in_(privy_ids),
        ]
        if term.isdigit():
            clauses.append(User.id == int(term))
        query = query.filter(or_(*clauses))

    total = query.count()
    rows = query.order_by(User.last_active_at.desc(), User.id.desc()).offset(offset).limit(limit).all()
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "users": [_user_summary(db, user) for user in rows],
    }


@router.get("/{user_id}")
def user_detail(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = _require_target(db, user_id)
    profile = db.query(UserTrustProfile).filter(UserTrustProfile.user_id == user.id).first()
    signals = db.query(FraudSignal).filter(FraudSignal.user_id == user.id).order_by(
        FraudSignal.created_at.desc(), FraudSignal.id.desc()
    ).limit(100).all()
    reviews = db.query(RiskReview).filter(RiskReview.user_id == user.id).order_by(
        RiskReview.created_at.desc(), RiskReview.id.desc()
    ).limit(100).all()
    binding = db.query(PrivyIdentityBinding).filter(PrivyIdentityBinding.user_id == user.id).first()
    social = db.query(SocialAccount).filter(SocialAccount.user_id == user.id).order_by(SocialAccount.provider).all()
    wallets = db.query(WalletConnection).filter(WalletConnection.user_id == user.id).order_by(
        WalletConnection.is_primary_interactive.desc(), WalletConnection.last_connected_at.desc()
    ).all()
    payouts = db.query(PayoutAddress).filter(PayoutAddress.user_id == user.id).order_by(
        PayoutAddress.is_primary.desc(), PayoutAddress.created_at.desc()
    ).all()
    sessions = db.query(UserSession).filter(UserSession.user_id == user.id).order_by(
        UserSession.created_at.desc(), UserSession.id.desc()
    ).limit(100).all()
    actions = db.query(AdminUserAction).filter(AdminUserAction.target_user_id == user.id).order_by(
        AdminUserAction.created_at.desc(), AdminUserAction.id.desc()
    ).limit(100).all()
    holds = db.query(UserRewardHold).filter(UserRewardHold.user_id == user.id).order_by(
        UserRewardHold.created_at.desc(), UserRewardHold.id.desc()
    ).limit(100).all()

    challenge_rows = db.query(ChallengeCompletion.status, func.count(ChallengeCompletion.id)).filter(
        ChallengeCompletion.user_id == user.id
    ).group_by(ChallengeCompletion.status).all()
    challenge_counts = {str(status): int(count) for status, count in challenge_rows}

    reward_rows = db.query(LedgerEntry.asset_symbol, LedgerEntry.status, func.sum(LedgerEntry.amount)).filter(
        LedgerEntry.user_id == user.id
    ).group_by(LedgerEntry.asset_symbol, LedgerEntry.status).all()
    rewards = [
        {"asset": asset, "status": status, "amount": str(Decimal(amount or 0))}
        for asset, status, amount in reward_rows
    ]
    withdrawal_rows = db.query(Withdrawal.status, func.count(Withdrawal.id)).filter(
        Withdrawal.user_id == user.id
    ).group_by(Withdrawal.status).all()

    verified_wallets = [wallet for wallet in wallets if wallet.verified_at]
    provider_names = {row.provider for row in social}
    approved_submissions = sum(challenge_counts.get(status, 0) for status in ("VERIFIED", "APPROVED"))
    account_age_days = max(0, (_now() - _as_utc(user.created_at)).days)
    positive_reasoning = []
    if verified_wallets:
        positive_reasoning.append(f"{len(verified_wallets)} cryptographically verified interactive wallet(s) on record")
    if "X" in provider_names:
        positive_reasoning.append("X identity currently linked through Privy")
    if "GOOGLE" in provider_names:
        positive_reasoning.append("Google identity currently linked through Privy")
    if approved_submissions:
        positive_reasoning.append(f"{approved_submissions} approved/verified Challenge submission(s)")
    positive_reasoning.append(f"Account age: {account_age_days} day(s)")

    return {
        "account": _user_summary(db, user),
        "identities": {
            "privy": ({
                "privy_user_id": binding.privy_user_id,
                "created_at": binding.created_at.isoformat(),
                "last_verified_at": binding.last_verified_at.isoformat(),
            } if binding else None),
            "providers": [{
                "provider": row.provider,
                "provider_user_id": row.provider_user_id,
                "username": row.username,
                "email": row.email,
                "display_name": row.display_name,
                "connected_at": row.connected_at.isoformat(),
                "last_verified_at": row.last_verified_at.isoformat(),
            } for row in social],
        },
        "wallets": [{
            "id": row.id,
            "address": row.address,
            "chain_type": row.chain_type,
            "chain_id": row.chain_id,
            "wallet_client_type": row.wallet_client_type,
            "connector_type": row.connector_type,
            "wallet_type": row.wallet_type,
            "verified": bool(row.verified_at),
            "verified_at": row.verified_at.isoformat() if row.verified_at else None,
            "is_interactive_signer": row.is_primary_interactive,
            "is_reward_destination": row.is_primary,
            "last_connected_at": row.last_connected_at.isoformat(),
        } for row in wallets],
        "payout_addresses": [{
            "id": row.id,
            "address": row.address,
            "chain": row.chain,
            "label": row.label,
            "is_reward_destination": row.is_primary,
            "verification_status": row.verification_status,
            "created_at": row.created_at.isoformat(),
        } for row in payouts],
        "trust": {
            "trust_level": profile.trust_level if profile else "NORMAL",
            "risk_score": int(profile.risk_score) if profile else 0,
            "risk_band": _risk_band(int(profile.risk_score) if profile else 0),
            "last_evaluated_at": profile.last_evaluated_at.isoformat() if profile else None,
            "reasoning": {
                "positive": positive_reasoning,
                "risk": [f"{row.severity}: {row.detail}" for row in signals if row.status == "OPEN"],
                "note": "Internal anti-Sybil weightings are intentionally not disclosed by this API.",
            },
            "signals": [{
                "id": row.id,
                "type": row.signal_type,
                "severity": row.severity,
                "detail": row.detail,
                "status": row.status,
                "created_at": row.created_at.isoformat(),
                "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
            } for row in signals],
            "review_history": [{
                "id": row.id,
                "trust_level": row.trust_level,
                "note": row.note,
                "reviewed_by_id": row.reviewed_by_id,
                "created_at": row.created_at.isoformat(),
            } for row in reviews],
        },
        "challenges": {"status_counts": challenge_counts},
        "rewards": {
            "balances_by_state": rewards,
            "withdrawal_status_counts": {str(status): int(count) for status, count in withdrawal_rows},
            "holds": [{
                "id": row.id,
                "status": row.status,
                "reason": row.reason,
                "created_by_id": row.created_by_id,
                "created_at": row.created_at.isoformat(),
                "released_by_id": row.released_by_id,
                "released_at": row.released_at.isoformat() if row.released_at else None,
                "release_reason": row.release_reason,
            } for row in holds],
        },
        "security": {
            "sessions": [{
                "session_id": row.session_id,
                "auth_method": row.auth_method,
                "created_at": row.created_at.isoformat(),
                "expires_at": row.expires_at.isoformat(),
                "last_seen_at": row.last_seen_at.isoformat(),
                "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
                "revoke_reason": row.revoke_reason,
            } for row in sessions],
        },
        "admin_actions": [{
            "id": row.id,
            "admin_user_id": row.admin_user_id,
            "action_type": row.action_type,
            "reason": row.reason,
            "before_state": row.before_state,
            "after_state": row.after_state,
            "created_at": row.created_at.isoformat(),
        } for row in actions],
    }


@router.patch("/{user_id}/state")
def change_account_state(
    user_id: int,
    data: AccountStateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = _require_target(db, user_id, lock=True)
    state = data.account_state.upper()
    if state not in ACCOUNT_STATES:
        raise HTTPException(400, "Invalid account state")
    if target.id == admin.id and state != target.account_state:
        raise HTTPException(409, "Admins cannot change their own account state through user moderation")
    before = {"account_state": target.account_state, "is_active": target.is_active}
    target.account_state = state
    target.is_active = state not in {"SUSPENDED", "DISQUALIFIED"}
    revoked = 0
    if state in {"SUSPENDED", "DISQUALIFIED"}:
        revoked = _revoke_sessions(db, target.id, f"Admin account state {state}: {data.reason.strip()}")
    after = {"account_state": target.account_state, "is_active": target.is_active, "sessions_revoked": revoked}
    _record_action(db, admin, target, "ACCOUNT_STATE_CHANGED", data.reason, before, after)
    db.commit()
    return {"user_id": target.id, **after}


@router.post("/{user_id}/sessions/revoke")
def revoke_sessions(
    user_id: int,
    data: SessionRevokeIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = _require_target(db, user_id, lock=True)
    if data.session_id:
        exists = db.query(UserSession.id).filter(
            UserSession.user_id == target.id,
            UserSession.session_id == data.session_id,
        ).first()
        if not exists:
            raise HTTPException(404, "Session not found for this user")
    revoked = _revoke_sessions(db, target.id, data.reason.strip(), data.session_id)
    _record_action(
        db, admin, target, "SESSIONS_REVOKED", data.reason,
        {"session_id": data.session_id},
        {"session_id": data.session_id, "sessions_revoked": revoked},
    )
    db.commit()
    return {"user_id": target.id, "sessions_revoked": revoked, "session_id": data.session_id}


@router.post("/{user_id}/rewards/hold")
def hold_rewards(
    user_id: int,
    data: ReasonIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = _require_target(db, user_id, lock=True)
    existing = _active_reward_hold(db, target.id)
    if existing:
        raise HTTPException(409, "Rewards are already held for this user")
    hold = UserRewardHold(user_id=target.id, reason=data.reason.strip(), created_by_id=admin.id)
    db.add(hold)
    db.flush()
    _record_action(db, admin, target, "REWARDS_HELD", data.reason, {"reward_hold": False}, {"reward_hold": True, "hold_id": hold.id})
    db.commit()
    return {"user_id": target.id, "reward_hold": True, "hold_id": hold.id}


@router.post("/{user_id}/rewards/release")
def release_rewards(
    user_id: int,
    data: ReasonIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = _require_target(db, user_id, lock=True)
    hold = _active_reward_hold(db, target.id)
    if not hold:
        raise HTTPException(409, "No active reward hold exists for this user")
    hold.status = "RELEASED"
    hold.released_by_id = admin.id
    hold.released_at = _now()
    hold.release_reason = data.reason.strip()
    _record_action(db, admin, target, "REWARDS_RELEASED", data.reason, {"reward_hold": True, "hold_id": hold.id}, {"reward_hold": False, "hold_id": hold.id})
    db.commit()
    return {"user_id": target.id, "reward_hold": False, "hold_id": hold.id}


@router.post("/{user_id}/trust/correct")
def correct_trust(
    user_id: int,
    data: TrustCorrectionIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = _require_target(db, user_id, lock=True)
    level = data.trust_level.upper()
    if level not in TRUST_LEVELS:
        raise HTTPException(400, "Invalid trust level")
    profile = db.query(UserTrustProfile).filter(UserTrustProfile.user_id == target.id).with_for_update().first()
    if not profile:
        profile = UserTrustProfile(user_id=target.id)
        db.add(profile)
        db.flush()
    before = {"trust_level": profile.trust_level, "risk_score": int(profile.risk_score), "account_state": target.account_state}
    profile.trust_level = level
    profile.reviewed_by_id = admin.id
    profile.updated_at = _now()
    db.add(RiskReview(
        user_id=target.id,
        reviewed_by_id=admin.id,
        trust_level=level,
        note=data.reason.strip(),
    ))
    after = {"trust_level": profile.trust_level, "risk_score": int(profile.risk_score), "account_state": target.account_state}
    _record_action(db, admin, target, "TRUST_CORRECTED", data.reason, before, after)
    db.commit()
    return {"user_id": target.id, **after}


@router.post("/{user_id}/signals/{signal_id}")
def decide_signal(
    user_id: int,
    signal_id: int,
    data: SignalDecisionIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = _require_target(db, user_id, lock=True)
    signal = db.query(FraudSignal).filter(
        FraudSignal.id == signal_id,
        FraudSignal.user_id == target.id,
    ).with_for_update().first()
    if not signal:
        raise HTTPException(404, "Risk signal not found for this user")
    state = data.status.upper()
    if state not in SIGNAL_STATES:
        raise HTTPException(400, "Signal status must be OPEN or RESOLVED")
    before = {"signal_id": signal.id, "status": signal.status, "resolved_at": signal.resolved_at.isoformat() if signal.resolved_at else None}
    signal.status = state
    signal.resolved_at = _now() if state == "RESOLVED" else None
    after = {"signal_id": signal.id, "status": signal.status, "resolved_at": signal.resolved_at.isoformat() if signal.resolved_at else None}
    _record_action(db, admin, target, "RISK_SIGNAL_UPDATED", data.reason, before, after)
    db.commit()
    return {"user_id": target.id, **after}
