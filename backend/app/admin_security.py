import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import UTC, datetime

from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from .admin_security_models import AdminAuditEvent, AdminMfaCredential, AdminPrivilegeSession
from .config import settings
from .models import User, UserSession

PRIVILEGE_HEADER = "X-NuBagz-Admin-Privilege"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _fernet() -> Fernet:
    raw = (settings.admin_security_key or "").strip()
    if not raw:
        if settings.environment.lower() == "production":
            raise RuntimeError("Production NuBagz requires ADMIN_SECURITY_KEY")
        raw = settings.signing_key
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)


def encrypt_mfa_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_mfa_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except Exception as exc:
        raise HTTPException(503, "Admin MFA credential cannot be decrypted") from exc


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _totp_counter(at: int | None = None) -> int:
    return int((at if at is not None else time.time()) // 30)


def _decode_base32(secret: str) -> bytes:
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode(padded, casefold=True)


def totp_code(secret: str, counter: int) -> str:
    digest = hmac.new(_decode_base32(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def verify_totp(secret: str, code: str, last_counter: int | None = None) -> int | None:
    clean = "".join(ch for ch in str(code) if ch.isdigit())
    if len(clean) != 6:
        return None
    current = _totp_counter()
    for counter in (current - 1, current, current + 1):
        if last_counter is not None and counter <= last_counter:
            continue
        if hmac.compare_digest(totp_code(secret, counter), clean):
            return counter
    return None


def privilege_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def record_admin_audit(
    db: Session,
    admin_user_id: int,
    event_type: str,
    *,
    user_session_id: str | None = None,
    privilege_session_id: int | None = None,
    request: Request | None = None,
    reason: str | None = None,
    details: dict | None = None,
    commit: bool = True,
) -> AdminAuditEvent:
    row = AdminAuditEvent(
        admin_user_id=admin_user_id,
        user_session_id=user_session_id,
        privilege_session_id=privilege_session_id,
        event_type=event_type,
        method=request.method.upper() if request else None,
        path=request.url.path if request else None,
        reason=reason,
        details=details,
    )
    db.add(row)
    if commit:
        db.commit()
    else:
        db.flush()
    return row


def get_mfa_credential(db: Session, user_id: int) -> AdminMfaCredential | None:
    return db.query(AdminMfaCredential).filter(AdminMfaCredential.user_id == user_id).first()


def active_privilege(
    db: Session,
    admin: User,
    user_session: UserSession,
    token: str | None,
    *,
    touch: bool = True,
) -> AdminPrivilegeSession | None:
    if not token:
        return None
    row = db.query(AdminPrivilegeSession).filter(
        AdminPrivilegeSession.token_hash == privilege_token_hash(token),
        AdminPrivilegeSession.admin_user_id == admin.id,
        AdminPrivilegeSession.user_session_id == user_session.session_id,
        AdminPrivilegeSession.revoked_at.is_(None),
    ).first()
    now = datetime.now(UTC)
    if not row or _as_utc(row.expires_at) <= now:
        return None
    if touch and (now - _as_utc(row.last_used_at)).total_seconds() >= 60:
        row.last_used_at = now
        db.commit()
    return row


def require_active_privilege(
    db: Session,
    admin: User,
    user_session: UserSession,
    token: str | None,
    request: Request | None = None,
) -> AdminPrivilegeSession:
    mfa = get_mfa_credential(db, admin.id)
    if not mfa or not mfa.enabled:
        record_admin_audit(
            db,
            admin.id,
            "PRIVILEGED_ACCESS_DENIED_MFA_REQUIRED",
            user_session_id=user_session.session_id,
            request=request,
        )
        raise HTTPException(428, "Admin MFA enrollment is required before sensitive operations")
    privilege = active_privilege(db, admin, user_session, token)
    if not privilege:
        record_admin_audit(
            db,
            admin.id,
            "PRIVILEGED_ACCESS_DENIED_REAUTH_REQUIRED",
            user_session_id=user_session.session_id,
            request=request,
        )
        raise HTTPException(428, "Short-lived privileged Admin reauthentication is required")
    return privilege
