from datetime import datetime, UTC
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.now(UTC)


class SwapIntent(Base):
    """Legacy draft-swap storage retained for compatibility with old databases."""

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


class SwapTrade(Base):
    """Executable aggregator route and genuine wallet transaction state.

    Token amounts are stored as decimal strings of integer base units. This is
    deliberate: ERC-20 uint256 quantities can exceed the integer capacity of a
    fixed NUMERIC(36,18) column and must not lose precision.
    """

    __tablename__ = "swap_trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    wallet_connection_id: Mapped[int] = mapped_column(ForeignKey("wallet_connections.id"), index=True)
    chain: Mapped[str] = mapped_column(String(32), index=True)
    chain_id: Mapped[int] = mapped_column(Integer, index=True)
    sell_asset: Mapped[str] = mapped_column(String(64))
    buy_asset: Mapped[str] = mapped_column(String(64))
    sell_amount_raw: Mapped[str] = mapped_column(String(96))
    quoted_buy_amount_raw: Mapped[str] = mapped_column(String(96))
    max_slippage_bps: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(32), default="QUOTED", index=True)
    provider_name: Mapped[str] = mapped_column(String(80), index=True)
    provider_quote_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quote_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    transaction_payload: Mapped[str] = mapped_column(Text)
    tx_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


# Legacy project-level Gas Pass tables are retained for historical compatibility.
# New sponsorship is challenge-scoped via GasSponsorshipPolicy/GasSponsorshipClaim.
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


class GasSponsorshipPolicy(Base):
    """Optional, project-funded gas sponsorship attached to one ONCHAIN Bag Work activity."""
    __tablename__ = "gas_sponsorship_policies"
    __table_args__ = (UniqueConstraint("challenge_id", name="uq_gas_policy_challenge"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    chain: Mapped[str] = mapped_column(String(32), index=True)
    native_asset: Mapped[str] = mapped_column(String(24))
    max_native_per_claim: Mapped[Decimal] = mapped_column(Numeric(36, 18))
    max_unique_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_claims: Mapped[int] = mapped_column(Integer)
    max_claims_per_wallet: Mapped[int] = mapped_column(Integer, default=1)
    funded_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18))
    spent_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), default=0)
    funding_reference: Mapped[str] = mapped_column(String(255))
    funding_status: Mapped[str] = mapped_column(String(24), default="DECLARED", index=True)
    status: Mapped[str] = mapped_column(String(24), default="FUNDING_PENDING", index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class GasSponsorshipClaim(Base):
    """Atomic reservation/execution record for one sponsored on-chain transaction."""
    __tablename__ = "gas_sponsorship_claims"
    __table_args__ = (UniqueConstraint("reservation_key", name="uq_gas_claim_reservation_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("gas_sponsorship_policies.id"), index=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    wallet_connection_id: Mapped[int] = mapped_column(ForeignKey("wallet_connections.id"), index=True)
    reservation_key: Mapped[str] = mapped_column(String(96), index=True)
    transaction_payload: Mapped[str] = mapped_column(Text)
    reserved_native_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18))
    gas_spent_native: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="RESERVED", index=True)
    provider_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reservation_expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
