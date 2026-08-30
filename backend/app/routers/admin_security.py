import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..admin_security import (
    PRIVILEGE_HEADER,
    active_privilege,
    decrypt_mfa_secret,
    encrypt_mfa_secret,
    get_mfa_credential,
    new_totp_secret,
    privilege_token_hash,
    record_admin_audit,
    require_active_privilege,
    verify_totp,
)
from ..admin_security_models import AdminAuditEvent, AdminMfaCredential, AdminPrivilegeSession
from ..config import settings
from ..db import get_db
from ..deps import get_current_session, require_admin_basic
from ..models import User, UserSession
from ..security import verify_password
from ..security_models import PrivyIdentityBinding
from ..social_auth import verify_privy_identity_token

router = APIRouter(prefix="/api/admin/security", tags=["admin-security"])


class ReauthIn(BaseModel):
    password: str | None = Field(default=None, max_length=512)
    identity_token: str | None = Field(default=None, max_length=12000)


class MfaConfirmIn(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class PrivilegeStartIn(ReauthIn):
    code: str = Field(min_length=6, max_length=16)


def _now() -> datetime:
    return datetime.now(UTC)


def _verify_primary_reauth(db: Session, admin: User, session: UserSession, data: ReauthIn) -> str:
    if session.auth_method == "PASSWORD":
        if not data.password or not verify_password(data.password, admin.password_hash):
            raise HTTPException(401, "Admin password reauthentication failed")
        return "PASSWORD_REAUTH"

    if session.auth_method == "PRIVY":
        if not data.identity_token:
            raise HTTPException(401, "Fresh Privy identity proof is required for Admin reauthentication")
        privy_user_id, _ = verify_privy_identity_token(data.identity_token)
        binding = db.query(PrivyIdentityBinding).filter(PrivyIdentityBinding.user_id == admin.id).first()
        if not binding or binding.privy_user_id != privy_user_id:
            raise HTTPException(401, "Privy identity does not match this Admin account")
        return "PRIVY_REAUTH"

    raise HTTPException(409, "This Admin authentication method cannot open a privileged session")


@router.get("/status")
def security_status(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_basic),
    session: UserSession = Depends(get_current_session),
    privilege_token: str | None = Header(default=None, alias=PRIVILEGE_HEADER),
):
    credential = get_mfa_credential(db, admin.id)
    privilege = active_privilege(db, admin, session, privilege_token, touch=False)
    return {
        "mfa_enrolled": bool(credential),
        "mfa_enabled": bool(credential and credential.enabled),
        "mfa_verified_at": credential.verified_at.isoformat() if credential and credential.verified_at else None,
        "auth_method": session.auth_method,
        "privileged": bool(privilege),
        "privilege_expires_at": privilege.expires_at.isoformat() if privilege else None,
        "privileged_minutes": settings.privileged_minutes,
    }


@router.post("/mfa/setup")
def setup_mfa(
    data: ReauthIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_basic),
    session: UserSession = Depends(get_current_session),
):
    factor = _verify_primary_reauth(db, admin, session, data)
    existing = get_mfa_credential(db, admin.id)
    if existing and existing.enabled:
        raise HTTPException(409, "Admin MFA is already enabled")
    secret = new_totp_secret()
    now = _now()
    if existing:
        existing.secret_ciphertext = encrypt_mfa_secret(secret)
        existing.enabled = False
        existing.last_counter = None
        existing.created_at = now
        existing.verified_at = None
        existing.disabled_at = None
        credential = existing
    else:
        credential = AdminMfaCredential(
            user_id=admin.id,
            secret_ciphertext=encrypt_mfa_secret(secret),
            enabled=False,
            created_at=now,
        )
        db.add(credential)
    db.flush()
    record_admin_audit(
        db, admin.id, "MFA_SETUP_STARTED",
        user_session_id=session.session_id,
        request=request,
        details={"primary_factor": factor},
        commit=False,
    )
    db.commit()
    issuer = "NuBagz"
    label = f"NuBagz:{admin.email}"
    uri = f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&digits=6&period=30"
    return {"secret": secret, "otpauth_uri": uri, "message": "Add this secret to your authenticator, then confirm one current code."}


@router.post("/mfa/confirm")
def confirm_mfa(
    data: MfaConfirmIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_basic),
    session: UserSession = Depends(get_current_session),
):
    credential = get_mfa_credential(db, admin.id)
    if not credential:
        raise HTTPException(409, "Start Admin MFA setup first")
    if credential.enabled:
        raise HTTPException(409, "Admin MFA is already enabled")
    secret = decrypt_mfa_secret(credential.secret_ciphertext)
    counter = verify_totp(secret, data.code, credential.last_counter)
    if counter is None:
        raise HTTPException(401, "Invalid or already-used authenticator code")
    credential.enabled = True
    credential.last_counter = counter
    credential.verified_at = _now()
    credential.disabled_at = None
    record_admin_audit(
        db, admin.id, "MFA_ENABLED",
        user_session_id=session.session_id,
        request=request,
        commit=False,
    )
    db.commit()
    return {"mfa_enabled": True, "verified_at": credential.verified_at.isoformat()}


@router.post("/privilege/start")
def start_privilege(
    data: PrivilegeStartIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_basic),
    session: UserSession = Depends(get_current_session),
):
    credential = get_mfa_credential(db, admin.id)
    if not credential or not credential.enabled:
        raise HTTPException(428, "Admin MFA enrollment is required before privileged reauthentication")
    primary_factor = _verify_primary_reauth(db, admin, session, data)
    secret = decrypt_mfa_secret(credential.secret_ciphertext)
    counter = verify_totp(secret, data.code, credential.last_counter)
    if counter is None:
        record_admin_audit(
            db, admin.id, "PRIVILEGE_REAUTH_FAILED",
            user_session_id=session.session_id,
            request=request,
            details={"primary_factor": primary_factor},
        )
        raise HTTPException(401, "Invalid or already-used authenticator code")
    credential.last_counter = counter
    now = _now()
    for row in db.query(AdminPrivilegeSession).filter(
        AdminPrivilegeSession.admin_user_id == admin.id,
        AdminPrivilegeSession.user_session_id == session.session_id,
        AdminPrivilegeSession.revoked_at.is_(None),
    ).all():
        row.revoked_at = now
        row.revoke_reason = "SUPERSEDED_BY_REAUTH"
    raw_token = secrets.token_urlsafe(48)
    privilege = AdminPrivilegeSession(
        token_hash=privilege_token_hash(raw_token),
        admin_user_id=admin.id,
        user_session_id=session.session_id,
        factors=[primary_factor, "TOTP"],
        issued_at=now,
        expires_at=now + timedelta(minutes=settings.privileged_minutes),
        last_used_at=now,
    )
    db.add(privilege)
    db.flush()
    record_admin_audit(
        db, admin.id, "PRIVILEGE_SESSION_STARTED",
        user_session_id=session.session_id,
        privilege_session_id=privilege.id,
        request=request,
        details={"factors": privilege.factors, "expires_at": privilege.expires_at.isoformat()},
        commit=False,
    )
    db.commit()
    return {"privilege_token": raw_token, "expires_at": privilege.expires_at.isoformat(), "factors": privilege.factors}


@router.post("/privilege/revoke")
def revoke_privilege(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_basic),
    session: UserSession = Depends(get_current_session),
    privilege_token: str | None = Header(default=None, alias=PRIVILEGE_HEADER),
):
    privilege = active_privilege(db, admin, session, privilege_token, touch=False)
    if privilege:
        privilege.revoked_at = _now()
        privilege.revoke_reason = "ADMIN_LOCKED_PRIVILEGED_SESSION"
        record_admin_audit(
            db, admin.id, "PRIVILEGE_SESSION_REVOKED",
            user_session_id=session.session_id,
            privilege_session_id=privilege.id,
            request=request,
            commit=False,
        )
        db.commit()
    return {"privileged": False}


@router.get("/audit")
def audit_log(
    request: Request,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_basic),
    session: UserSession = Depends(get_current_session),
    privilege_token: str | None = Header(default=None, alias=PRIVILEGE_HEADER),
):
    privilege = require_active_privilege(db, admin, session, privilege_token, request)
    limit = max(1, min(int(limit), 250))
    offset = max(0, int(offset))
    query = db.query(AdminAuditEvent)
    if event_type:
        query = query.filter(AdminAuditEvent.event_type == event_type.upper())
    total = query.count()
    rows = query.order_by(AdminAuditEvent.created_at.desc(), AdminAuditEvent.id.desc()).offset(offset).limit(limit).all()
    return {
        "total": int(total),
        "events": [{
            "id": row.id,
            "admin_user_id": row.admin_user_id,
            "user_session_id": row.user_session_id,
            "privilege_session_id": row.privilege_session_id,
            "event_type": row.event_type,
            "method": row.method,
            "path": row.path,
            "reason": row.reason,
            "details": row.details,
            "created_at": row.created_at.isoformat(),
        } for row in rows],
        "privilege_session_id": privilege.id,
    }
