from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now():
    return datetime.now(UTC)


class AdminUserAction(Base):
    """Append-only focused audit record for sensitive Phase 2.3 user actions.

    Phase 2.5 will introduce the broader privileged Admin audit layer. This table
    intentionally records the mandatory reason and before/after state for user
    moderation actions now, without pretending that the comprehensive audit
    programme already exists.
    """

    __tablename__ = "admin_user_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(64), index=True)
    reason: Mapped[str] = mapped_column(Text)
    before_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class UserRewardHold(Base):
    """Historical payout hold record.

    A hold does not rewrite earned ledger rows or imply that a pending Project
    Reward has settled. It blocks new withdrawals/payout progression while the
    hold is ACTIVE, then remains as immutable history after release.
    """

    __tablename__ = "user_reward_holds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", index=True)
    reason: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    released_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
