from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..abuse_models import SecurityEvent
from ..admin_permissions import permissions_for
from ..admin_user_models import AdminUserAction
from ..challenge_models import SocialAccount
from ..db import get_db
from ..deps import require_admin
from ..models import PayoutAddress, User, UserSession, WalletConnection
from ..security_hardening import hash_network_identifier, trusted_client_ip
from ..security_models import PrivyIdentityBinding

router = APIRouter(prefix="/api/admin/recovery", tags=["admin-recovery"])


class ReasonIn(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class ConnectedLoginReplacementIn(ReasonIn):
    new_privy_user_id: str = Field(min_length=8, max_length=255)


class RetireWalletIn(ReasonIn):
    replacement_wallet_id: int | None = Field(default=None, ge=1)


def _now() -> datetime:
    return datetime.now(UTC)


def _target(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if not user:
        raise HTTPException(404, "User not found")
    return user


def _revoke_sessions(db: Session, user_id: int, reason: str) -> int:
    rows = db.query(UserSession).filter(
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
    ).all()
    now = _now()
    for row in rows:
        row.revoked_at = now
        row.revoke_reason = reason[:255]
    return len(rows)


def _security_event(db: Session, request: Request, user_id: int, event_type: str, detail: str) -> None:
    db.add(SecurityEvent(
        user_id=user_id,
        ip_hash=hash_network_identifier(trusted_client_ip(request)),
        event_type=event_type[:64],
        route_group="RECOVERY",
        detail=detail[:2000],
        created_at=_now(),
    ))


def _admin_action(
    db: Session,
    admin: User,
    target: User,
    action_type: str,
    reason: str,
    before_state: dict | None,
    after_state: dict | None,
) -> None:
    db.add(AdminUserAction(
        admin_user_id=admin.id,
        target_user_id=target.id,
        action_type=action_type,
        reason=reason.strip(),
        before_state=before_state,
        after_state=after_state,
    ))


@router.get("/permissions")
def my_admin_permissions(admin: User = Depends(require_admin)):
    return {"role": admin.role, "permissions": sorted(permissions_for(admin))}


@router.get("/users/{user_id}/history")
def user_security_history(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    rows = db.query(SecurityEvent).filter(SecurityEvent.user_id == user_id).order_by(
        SecurityEvent.created_at.desc(), SecurityEvent.id.desc()
    ).limit(250).all()
    return {
        "user_id": user_id,
        "role": admin.role,
        "permissions": sorted(permissions_for(admin)),
        "events": [{
            "id": row.id,
            "event_type": row.event_type,
            "route_group": row.route_group,
            "detail": row.detail,
            "created_at": row.created_at.isoformat(),
        } for row in rows],
    }


@router.post("/users/{user_id}/connected-login/replace")
def replace_connected_login(
    user_id: int,
    data: ConnectedLoginReplacementIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = _target(db, user_id)
    if target.id == admin.id:
        raise HTTPException(409, "Use a second authorised Admin for recovery of your own connected login")

    new_did = data.new_privy_user_id.strip()
    owner = db.query(PrivyIdentityBinding).filter(PrivyIdentityBinding.privy_user_id == new_did).first()
    if owner and owner.user_id != target.id:
        raise HTTPException(409, "That Privy identity is already bound to another NuBagz user")

    binding = db.query(PrivyIdentityBinding).filter(PrivyIdentityBinding.user_id == target.id).first()
    old_did = binding.privy_user_id if binding else None
    if old_did == new_did:
        raise HTTPException(409, "The replacement Privy identity is already bound to this account")

    now = _now()
    if binding:
        binding.privy_user_id = new_did
        binding.last_verified_at = now
    else:
        db.add(PrivyIdentityBinding(
            user_id=target.id,
            privy_user_id=new_did,
            created_at=now,
            last_verified_at=now,
        ))

    # X/Google provider rows belong to the old Privy identity. The next login
    # through the replacement DID repopulates them from Privy's signed token.
    removed_social = db.query(SocialAccount).filter(SocialAccount.user_id == target.id).delete(synchronize_session=False)
    revoked = _revoke_sessions(db, target.id, f"Connected login replaced by Admin: {data.reason.strip()}")

    before = {"privy_user_id": old_did, "linked_social_accounts": int(removed_social)}
    after = {"privy_user_id": new_did, "linked_social_accounts": 0, "sessions_revoked": revoked}
    _admin_action(db, admin, target, "CONNECTED_LOGIN_REPLACED", data.reason, before, after)
    _security_event(
        db,
        request,
        target.id,
        "CONNECTED_LOGIN_REPLACED",
        f"Canonical Privy login was replaced after support investigation; {revoked} active session(s) revoked and provider links cleared for resync.",
    )
    db.commit()
    return {"user_id": target.id, **after}


@router.post("/users/{user_id}/wallets/{wallet_id}/retire")
def retire_compromised_wallet(
    user_id: int,
    wallet_id: int,
    data: RetireWalletIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = _target(db, user_id)
    if target.id == admin.id:
        raise HTTPException(409, "Use a second authorised Admin for recovery of your own wallet linkage")
    wallet = db.query(WalletConnection).filter(
        WalletConnection.id == wallet_id,
        WalletConnection.user_id == target.id,
    ).first()
    if not wallet:
        raise HTTPException(404, "Wallet linkage not found")

    replacement = None
    if data.replacement_wallet_id is not None:
        if data.replacement_wallet_id == wallet.id:
            raise HTTPException(400, "Replacement wallet must be different from the compromised wallet")
        replacement = db.query(WalletConnection).filter(
            WalletConnection.id == data.replacement_wallet_id,
            WalletConnection.user_id == target.id,
            WalletConnection.verified_at.isnot(None),
        ).first()
        if not replacement:
            raise HTTPException(404, "Verified replacement wallet not found")

    before = {
        "wallet_id": wallet.id,
        "address": wallet.address,
        "verified": bool(wallet.verified_at),
        "interactive_signer": bool(wallet.is_primary_interactive),
        "reward_destination": bool(wallet.is_primary),
    }

    if wallet.is_primary_interactive:
        db.query(WalletConnection).filter(WalletConnection.user_id == target.id).update(
            {WalletConnection.is_primary_interactive: False}, synchronize_session=False
        )
        if replacement:
            replacement.is_primary_interactive = True

    if wallet.is_primary:
        db.query(WalletConnection).filter(WalletConnection.user_id == target.id).update(
            {WalletConnection.is_primary: False}, synchronize_session=False
        )
        db.query(PayoutAddress).filter(PayoutAddress.user_id == target.id).update(
            {PayoutAddress.is_primary: False}, synchronize_session=False
        )
        if replacement:
            replacement.is_primary = True
            target.wallet_address = replacement.address
            target.wallet_chain = "EVM"
        else:
            target.wallet_address = None
            target.wallet_chain = None

    compromised_address = wallet.address
    db.delete(wallet)
    revoked = _revoke_sessions(db, target.id, f"Compromised wallet linkage retired by Admin: {data.reason.strip()}")
    after = {
        "retired_wallet_id": wallet_id,
        "replacement_wallet_id": replacement.id if replacement else None,
        "replacement_address": replacement.address if replacement else None,
        "sessions_revoked": revoked,
    }
    _admin_action(db, admin, target, "COMPROMISED_WALLET_RETIRED", data.reason, before, after)
    _security_event(
        db,
        request,
        target.id,
        "COMPROMISED_WALLET_RETIRED",
        f"Wallet {compromised_address} was retired from NuBagz signer/reward roles; {revoked} active session(s) revoked. Replacement: {replacement.address if replacement else 'user must verify a new wallet'}.",
    )
    db.commit()
    return {"user_id": target.id, **after}
