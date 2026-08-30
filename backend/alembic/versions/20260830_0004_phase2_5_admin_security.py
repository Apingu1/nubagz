"""Phase 2.5 privileged Admin security and broad audit.

Revision ID: 20260830_0004
Revises: 20260830_0003
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260830_0004"
down_revision = "20260830_0003"
branch_labels = None
depends_on = None


def _indexes(table: str) -> set[str]:
    return {row["name"] for row in inspect(op.get_bind()).get_indexes(table) if row.get("name")}


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "admin_mfa_credentials" not in tables:
        op.create_table(
            "admin_mfa_credentials",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("secret_ciphertext", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("last_counter", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("disabled_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("user_id", name="uq_admin_mfa_user"),
        )
    if "ix_admin_mfa_credentials_user_id" not in _indexes("admin_mfa_credentials"):
        op.create_index("ix_admin_mfa_credentials_user_id", "admin_mfa_credentials", ["user_id"])
    if "ix_admin_mfa_credentials_enabled" not in _indexes("admin_mfa_credentials"):
        op.create_index("ix_admin_mfa_credentials_enabled", "admin_mfa_credentials", ["enabled"])
    if "ix_admin_mfa_credentials_created_at" not in _indexes("admin_mfa_credentials"):
        op.create_index("ix_admin_mfa_credentials_created_at", "admin_mfa_credentials", ["created_at"])

    tables = set(inspect(op.get_bind()).get_table_names())
    if "admin_privilege_sessions" not in tables:
        op.create_table(
            "admin_privilege_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
            sa.Column("admin_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("user_session_id", sa.String(length=64), nullable=False),
            sa.Column("factors", sa.JSON(), nullable=False),
            sa.Column("issued_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("revoke_reason", sa.String(length=255), nullable=True),
        )
    for name, columns in {
        "ix_admin_privilege_sessions_token_hash": ["token_hash"],
        "ix_admin_privilege_sessions_admin_user_id": ["admin_user_id"],
        "ix_admin_privilege_sessions_user_session_id": ["user_session_id"],
        "ix_admin_privilege_sessions_issued_at": ["issued_at"],
        "ix_admin_privilege_sessions_expires_at": ["expires_at"],
        "ix_admin_privilege_sessions_revoked_at": ["revoked_at"],
    }.items():
        if name not in _indexes("admin_privilege_sessions"):
            op.create_index(name, "admin_privilege_sessions", columns)

    tables = set(inspect(op.get_bind()).get_table_names())
    if "admin_audit_events" not in tables:
        op.create_table(
            "admin_audit_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("admin_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("user_session_id", sa.String(length=64), nullable=True),
            sa.Column("privilege_session_id", sa.Integer(), sa.ForeignKey("admin_privilege_sessions.id"), nullable=True),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("method", sa.String(length=12), nullable=True),
            sa.Column("path", sa.String(length=500), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    for name, columns in {
        "ix_admin_audit_events_admin_user_id": ["admin_user_id"],
        "ix_admin_audit_events_user_session_id": ["user_session_id"],
        "ix_admin_audit_events_privilege_session_id": ["privilege_session_id"],
        "ix_admin_audit_events_event_type": ["event_type"],
        "ix_admin_audit_events_path": ["path"],
        "ix_admin_audit_events_created_at": ["created_at"],
    }.items():
        if name not in _indexes("admin_audit_events"):
            op.create_index(name, "admin_audit_events", columns)


def downgrade() -> None:
    # Forward-only security migration. Dropping MFA/privilege/audit history would
    # weaken security evidence and is intentionally unsupported.
    pass
