"""Phase 2.1 security, session, signer and reward-truth foundation.

Revision ID: 20260829_0002
Revises: 20260829_0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260829_0002"
down_revision = "20260829_0001"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {row["name"] for row in inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {row["name"] for row in inspect(op.get_bind()).get_indexes(table) if row.get("name")}


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())

    if "users" in tables and "account_state" not in _columns("users"):
        op.add_column("users", sa.Column("account_state", sa.String(length=24), nullable=False, server_default="ACTIVE"))
        op.execute("UPDATE users SET account_state = CASE WHEN is_active = TRUE THEN 'ACTIVE' ELSE 'SUSPENDED' END")
    if "users" in tables and "ix_users_account_state" not in _indexes("users"):
        op.create_index("ix_users_account_state", "users", ["account_state"], unique=False)

    if "wallet_connections" in tables and "is_primary_interactive" not in _columns("wallet_connections"):
        op.add_column("wallet_connections", sa.Column("is_primary_interactive", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "wallet_connections" in tables:
        op.execute("""
            UPDATE wallet_connections
            SET is_primary_interactive = is_primary
            WHERE verified_at IS NOT NULL
        """)
        op.execute("""
            WITH ranked AS (
                SELECT id, user_id,
                       ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY last_connected_at DESC, id DESC) AS rn
                FROM wallet_connections
                WHERE verified_at IS NOT NULL
            ), users_without_signer AS (
                SELECT DISTINCT r.user_id
                FROM ranked r
                WHERE NOT EXISTS (
                    SELECT 1 FROM wallet_connections w
                    WHERE w.user_id = r.user_id AND w.is_primary_interactive = TRUE
                )
            )
            UPDATE wallet_connections
            SET is_primary_interactive = TRUE
            WHERE id IN (
                SELECT r.id FROM ranked r
                JOIN users_without_signer u ON u.user_id = r.user_id
                WHERE r.rn = 1
            )
        """)
        if "ix_wallet_connections_is_primary_interactive" not in _indexes("wallet_connections"):
            op.create_index("ix_wallet_connections_is_primary_interactive", "wallet_connections", ["is_primary_interactive"], unique=False)

    # The Phase 1 compatibility ledger recorded approved Project Rewards as
    # AVAILABLE even though no blockchain settlement existed. Preserve the
    # earned record but make its state truthful until Phase 9 settlement.
    if "ledger_entries" in tables:
        op.execute("""
            UPDATE ledger_entries
            SET status = 'PENDING_SETTLEMENT'
            WHERE entry_type = 'CAMPAIGN_REWARD' AND status = 'AVAILABLE'
        """)


def downgrade() -> None:
    # Forward-only safety migration. Removing account/session semantics or
    # turning pending rewards back into AVAILABLE would recreate the defect.
    pass
