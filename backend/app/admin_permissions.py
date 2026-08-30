from __future__ import annotations

from .models import User


PLATFORM_ADMIN = "platform.admin"
USERS_VIEW = "users.view"
ACCOUNT_STATE_MANAGE = "users.account_state.manage"
TRUST_REVIEW = "trust.review"
REWARD_HOLD = "rewards.hold"
SESSION_REVOKE = "sessions.revoke"
RECOVERY_MANAGE = "recovery.manage"
SECURITY_AUDIT = "security.audit"

ADMIN_PERMISSIONS = {
    PLATFORM_ADMIN,
    USERS_VIEW,
    ACCOUNT_STATE_MANAGE,
    TRUST_REVIEW,
    REWARD_HOLD,
    SESSION_REVOKE,
    RECOVERY_MANAGE,
    SECURITY_AUDIT,
}

# SUPPORT is intentionally read-only in Phase 2. It gives an authorised support
# operator the investigation view without inheriting moderation/recovery powers.
# Any future widening of this role is an explicit permission change rather than a
# side-effect of being able to reach an /admin route.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "ADMIN": ADMIN_PERMISSIONS,
    "SUPPORT": {USERS_VIEW},
}


def permissions_for(user: User) -> set[str]:
    return set(ROLE_PERMISSIONS.get(str(user.role or "").upper(), set()))


def has_permission(user: User, permission: str) -> bool:
    return permission in permissions_for(user)


def permission_for_request(path: str, method: str) -> str:
    """Map existing Admin endpoints to explicit permission scopes.

    Unknown privileged surfaces fail into PLATFORM_ADMIN so adding a new Admin
    endpoint never accidentally grants it to a narrower support role.
    """
    path = path.rstrip("/") or "/"
    method = method.upper()
    safe = method in {"GET", "HEAD", "OPTIONS"}

    if path.startswith("/api/admin/users"):
        if safe:
            return USERS_VIEW
        if path.endswith("/state"):
            return ACCOUNT_STATE_MANAGE
        if "/trust/" in path or "/signals/" in path:
            return TRUST_REVIEW
        if "/rewards/" in path:
            return REWARD_HOLD
        if path.endswith("/sessions/revoke"):
            return SESSION_REVOKE
        return PLATFORM_ADMIN

    if path.startswith("/api/admin/recovery"):
        return USERS_VIEW if safe else RECOVERY_MANAGE

    if path.startswith("/api/risk/admin"):
        return USERS_VIEW if safe else TRUST_REVIEW

    return PLATFORM_ADMIN
