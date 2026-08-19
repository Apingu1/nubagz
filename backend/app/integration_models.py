from datetime import datetime, UTC
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.now(UTC)


class SwapIntent(Base):
    __tablename__ = "swap_intents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    wallet_connection_id: Mapped[int] = mapped_column(ForeignKey("wallet_connections.id"), index=True)
    chain: Mapped[str] = mapped_column(String(32), index=True)
    sell_asset: Mapped[str] = mapped_column(String(64))
    buy_asset: Mapped[str] = mapped_column(String(64))
    sell_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18))
    max_slippage_bps: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    provider_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_quote_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quoted_buy_amount: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
    quote_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    transaction_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class GasSponsorshipBudget(Base):
    __tablename__ = "gas_sponsorship_budgets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    chain: Mapped[str] = mapped_column(String(32), index=True)
    native_asset: Mapped[str] = mapped_column(String(24))
    amount_per_tx: Mapped[Decimal] = mapped_column(Numeric(36, 18))
    max_transactions: Mapped[int] = mapped_column(Integer)
    executed_transactions: Mapped[int] = mapped_column(Integer, default=0)
    funded_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18))
    spent_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), default=0)
    funding_reference: Mapped[str] = mapped_column(String(255))
    funding_status: Mapped[str] = mapped_column(String(24), default="DECLARED", index=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class GasSponsorshipRequest(Base):
    __tablename__ = "gas_sponsorship_requests"
    __table_args__ = (UniqueConstraint("budget_id", "user_id", name="uq_gas_budget_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("gas_sponsorship_budgets.id"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    wallet_connection_id: Mapped[int] = mapped_column(ForeignKey("wallet_connections.id"), index=True)
    transaction_payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    provider_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gas_spent_native: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
