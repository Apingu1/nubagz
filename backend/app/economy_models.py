from datetime import datetime, UTC
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.now(UTC)


class CampaignFunding(Base):
    __tablename__ = "campaign_funding"
    __table_args__ = (UniqueConstraint("campaign_id", name="uq_campaign_funding_campaign"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    declared_amount: Mapped[Decimal] = mapped_column(Numeric(36, 8), default=0)
    verified_amount: Mapped[Decimal] = mapped_column(Numeric(36, 8), default=0)
    tx_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="DECLARED", index=True)
    verified_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class AssetPriceSnapshot(Base):
    __tablename__ = "asset_price_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_symbol: Mapped[str] = mapped_column(String(24), index=True)
    price_gbp: Mapped[Decimal] = mapped_column(Numeric(36, 12))
    source: Mapped[str] = mapped_column(String(64), default="MANUAL")
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class BagDrop(Base):
    __tablename__ = "bag_drops"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    rarity: Mapped[str] = mapped_column(String(20), default="COMMON", index=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    max_claims: Mapped[int] = mapped_column(Integer, default=100)
    claims_count: Mapped[int] = mapped_column(Integer, default=0)
    min_bag_score: Mapped[int] = mapped_column(Integer, default=0)
    funding_tx_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    funding_status: Mapped[str] = mapped_column(String(24), default="DECLARED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class BagDropItem(Base):
    __tablename__ = "bag_drop_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drop_id: Mapped[int] = mapped_column(ForeignKey("bag_drops.id"), index=True)
    asset_symbol: Mapped[str] = mapped_column(String(24), index=True)
    amount_per_claim: Mapped[Decimal] = mapped_column(Numeric(36, 8))
    funded_amount: Mapped[Decimal] = mapped_column(Numeric(36, 8))
    distributed_amount: Mapped[Decimal] = mapped_column(Numeric(36, 8), default=0)


class BagDropClaim(Base):
    __tablename__ = "bag_drop_claims"
    __table_args__ = (UniqueConstraint("drop_id", "user_id", name="uq_bagdrop_user_claim"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drop_id: Mapped[int] = mapped_column(ForeignKey("bag_drops.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    claimed_at: Mapped[datetime] = mapped_column(DateTime, default=now)
