"""Phase 2.6 anti-abuse observations and security event evidence.

Revision ID: 20260830_0005
Revises: 20260830_0004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260830_0005"
down_revision = "20260830_0004"
branch_labels = None
depends_on = None


def _indexes(table: str) -> set[str]:
    return {row["name"] for row in inspect(op.get_bind()).get_indexes(table) if row.get("name")}


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "network_observations" not in tables:
        op.create_table(
            "network_observations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("ip_hash", sa.String(length=64), nullable=False),
            sa.Column("day_bucket", sa.String(length=10), nullable=False),
            sa.Column("request_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "ip_hash", "day_bucket", name="uq_user_network_day"),
        )
    for name, columns in {
        "ix_network_observations_user_id": ["user_id"],
        "ix_network_observations_ip_hash": ["ip_hash"],
        "ix_network_observations_day_bucket": ["day_bucket"],
        "ix_network_observations_last_seen_at": ["last_seen_at"],
    }.items():
        if name not in _indexes("network_observations"):
            op.create_index(name, "network_observations", columns)

    tables = set(inspect(op.get_bind()).get_table_names())
    if "security_events" not in tables:
        op.create_table(
            "security_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("ip_hash", sa.String(length=64), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("route_group", sa.String(length=64), nullable=False),
            sa.Column("detail", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    for name, columns in {
        "ix_security_events_user_id": ["user_id"],
        "ix_security_events_ip_hash": ["ip_hash"],
        "ix_security_events_event_type": ["event_type"],
        "ix_security_events_route_group": ["route_group"],
        "ix_security_events_created_at": ["created_at"],
    }.items():
        if name not in _indexes("security_events"):
            op.create_index(name, "security_events", columns)


def downgrade() -> None:
    # Forward-only security evidence migration. Removing anti-abuse observations
    # would erase investigation history and is intentionally unsupported.
    pass
