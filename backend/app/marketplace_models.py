from datetime import datetime, UTC
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.now(UTC)


class BagBuilderPathway(Base):
    __tablename__ = "bagbuilder_pathways"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    summary: Mapped[str] = mapped_column(Text)
    creator_share_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=0)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BagBuilderAttribution(Base):
    __tablename__ = "bagbuilder_attributions"
    __table_args__ = (UniqueConstraint("campaign_id", "user_id", name="uq_builder_campaign_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pathway_id: Mapped[int] = mapped_column(ForeignKey("bagbuilder_pathways.id"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Bounty(Base):
    __tablename__ = "bounties"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    reward_asset: Mapped[str] = mapped_column(String(24))
    reward_per_winner: Mapped[Decimal] = mapped_column(Numeric(36, 8))
    max_winners: Mapped[int] = mapped_column(Integer)
    winners_count: Mapped[int] = mapped_column(Integer, default=0)
    funded_amount: Mapped[Decimal] = mapped_column(Numeric(36, 8))
    distributed_amount: Mapped[Decimal] = mapped_column(Numeric(36, 8), default=0)
    funding_reference: Mapped[str] = mapped_column(String(255))
    funding_status: Mapped[str] = mapped_column(String(24), default="DECLARED", index=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class BountySubmission(Base):
    __tablename__ = "bounty_submissions"
    __table_args__ = (UniqueConstraint("bounty_id", "user_id", name="uq_bounty_user_submission"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bounty_id: Mapped[int] = mapped_column(ForeignKey("bounties.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    evidence: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class RevenueShareDistribution(Base):
    __tablename__ = "revenue_share_distributions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    asset_symbol: Mapped[str] = mapped_column(String(24))
    funded_amount: Mapped[Decimal] = mapped_column(Numeric(36, 8))
    distributed_amount: Mapped[Decimal] = mapped_column(Numeric(36, 8), default=0)
    funding_reference: Mapped[str] = mapped_column(String(255))
    funding_status: Mapped[str] = mapped_column(String(24), default="DECLARED", index=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    amount_per_recipient: Mapped[Decimal | None] = mapped_column(Numeric(36, 8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RevenueShareRecipient(Base):
    __tablename__ = "revenue_share_recipients"
    __table_args__ = (UniqueConstraint("distribution_id", "user_id", name="uq_revenue_share_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    distribution_id: Mapped[int] = mapped_column(ForeignKey("revenue_share_distributions.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
