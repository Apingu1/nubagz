from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now():
    return datetime.now(UTC)


class AdminMfaCredential(Base):
    __tablename__ = "admin_mfa_credentials"
    __table_args__ = (UniqueConstraint("user_id", name="uq_admin_mfa_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    secret_ciphertext: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AdminPrivilegeSession(Base):
    __tablename__ = "admin_privilege_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_session_id: Mapped[str] = mapped_column(String(64), index=True)
    factors: Mapped[list] = mapped_column(JSON, default=list)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AdminAuditEvent(Base):
    """Append-only broad Admin security/audit record.

    Detailed moderation before/after state remains in AdminUserAction. This table
    adds the cross-Admin security timeline: access to Admin routes, MFA events,
    privileged-session lifecycle, and sensitive route attempts.
    """

    __tablename__ = "admin_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    privilege_session_id: Mapped[int | None] = mapped_column(ForeignKey("admin_privilege_sessions.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    method: Mapped[str | None] = mapped_column(String(12), nullable=True)
    path: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
