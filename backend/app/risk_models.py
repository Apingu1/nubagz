from datetime import datetime, UTC
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.now(UTC)


class UserTrustProfile(Base):
    __tablename__ = "user_trust_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_trust_profile"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    trust_level: Mapped[str] = mapped_column(String(24), default="NORMAL", index=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class FraudSignal(Base):
    __tablename__ = "fraud_signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    signal_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    detail: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
