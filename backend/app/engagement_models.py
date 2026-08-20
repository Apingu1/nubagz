from datetime import datetime, UTC
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.now(UTC)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_notification_user_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    notification_type: Mapped[str] = mapped_column(String(48), index=True)
    title: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    link_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CampaignTemplate(Base):
    __tablename__ = "campaign_templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), default="LEARN")
    difficulty: Mapped[str] = mapped_column(String(24), default="EASY")
    user_share_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=80)
    nubagz_share_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=15)
    referral_share_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=5)
    default_max_users: Mapped[int] = mapped_column(Integer, default=1000)
    mission_blueprint: Mapped[str] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ProjectReview(Base):
    __tablename__ = "project_reviews"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_review_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    review: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="PUBLISHED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class SafetyReport(Base):
    __tablename__ = "safety_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(24), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    category: Mapped[str] = mapped_column(String(48), index=True)
    detail: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    resolution_action: Mapped[str] = mapped_column(String(48), default="NONE")
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DisputeMessage(Base):
    __tablename__ = "dispute_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("safety_reports.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class WatchBag(Base):
    __tablename__ = "watch_bag"
    __table_args__ = (UniqueConstraint("user_id", "campaign_id", name="uq_watch_bag_user_campaign"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ReferralConversion(Base):
    __tablename__ = "referral_conversions"
    __table_args__ = (UniqueConstraint("referred_user_id", "campaign_id", name="uq_referral_conversion_user_campaign"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referrer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    referred_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    asset_symbol: Mapped[str] = mapped_column(String(24), index=True)
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(36, 8), default=0)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(36, 8), default=0)
    status: Mapped[str] = mapped_column(String(24), default="PAID", index=True)
    reason: Mapped[str] = mapped_column(String(255), default="Funded referral conversion")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
