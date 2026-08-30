"""Phase 2.3 Admin Users backend controls.

Revision ID: 20260830_0003
Revises: 20260829_0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260830_0003"
down_revision = "20260829_0002"
branch_labels = None
depends_on = None


def _indexes(table: str) -> set[str]:
    return {row["name"] for row in inspect(op.get_bind()).get_indexes(table) if row.get("name")}


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())

    if "admin_user_actions" not in tables:
        op.create_table(
            "admin_user_actions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("admin_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("target_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("action_type", sa.String(length=64), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("before_state", sa.JSON(), nullable=True),
            sa.Column("after_state", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if "ix_admin_user_actions_admin_user_id" not in _indexes("admin_user_actions"):
        op.create_index("ix_admin_user_actions_admin_user_id", "admin_user_actions", ["admin_user_id"])
    if "ix_admin_user_actions_target_user_id" not in _indexes("admin_user_actions"):
        op.create_index("ix_admin_user_actions_target_user_id", "admin_user_actions", ["target_user_id"])
    if "ix_admin_user_actions_action_type" not in _indexes("admin_user_actions"):
        op.create_index("ix_admin_user_actions_action_type", "admin_user_actions", ["action_type"])
    if "ix_admin_user_actions_created_at" not in _indexes("admin_user_actions"):
        op.create_index("ix_admin_user_actions_created_at", "admin_user_actions", ["created_at"])

    tables = set(inspect(op.get_bind()).get_table_names())
    if "user_reward_holds" not in tables:
        op.create_table(
            "user_reward_holds",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("released_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("released_at", sa.DateTime(), nullable=True),
            sa.Column("release_reason", sa.Text(), nullable=True),
        )
    if "ix_user_reward_holds_user_id" not in _indexes("user_reward_holds"):
        op.create_index("ix_user_reward_holds_user_id", "user_reward_holds", ["user_id"])
    if "ix_user_reward_holds_status" not in _indexes("user_reward_holds"):
        op.create_index("ix_user_reward_holds_status", "user_reward_holds", ["status"])
    if "ix_user_reward_holds_created_by_id" not in _indexes("user_reward_holds"):
        op.create_index("ix_user_reward_holds_created_by_id", "user_reward_holds", ["created_by_id"])
    if "ix_user_reward_holds_created_at" not in _indexes("user_reward_holds"):
        op.create_index("ix_user_reward_holds_created_at", "user_reward_holds", ["created_at"])
    if "ix_user_reward_holds_released_at" not in _indexes("user_reward_holds"):
        op.create_index("ix_user_reward_holds_released_at", "user_reward_holds", ["released_at"])


def downgrade() -> None:
    # Forward-only safety migration. Removing moderation history or reward-hold
    # history would undermine investigation/audit continuity.
    pass
