from datetime import datetime, UTC
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
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
