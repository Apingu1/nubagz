from datetime import datetime, UTC
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.now(UTC)


class SocialAccount(Base):
    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_social_provider_identity"),
        UniqueConstraint("user_id", "provider", name="uq_user_social_provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(24), index=True)
    provider_user_id: Mapped[str] = mapped_column(String(255), index=True)
    privy_user_id: Mapped[str] = mapped_column(String(255), index=True)
    username: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_picture_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Challenge(Base):
    """Universal Bag Work activity.

    Campaign remains the funded reward container for backwards compatibility. New
    work of every kind (social, community, content, on-chain, project work and
    custom) is represented by this one model.
    """

    __tablename__ = "challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="BAG_WORK", index=True)
    provider: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    action: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    verification_type: Mapped[str] = mapped_column(String(32), default="PROJECT_REVIEW", index=True)
    target_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    xp_reward: Mapped[int] = mapped_column(Integer, default=50)
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ChallengeCompletion(Base):
    __tablename__ = "challenge_completions"
    __table_args__ = (UniqueConstraint("user_id", "challenge_id", name="uq_user_challenge"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
