from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now():
    return datetime.now(UTC)


class NetworkObservation(Base):
    """Privacy-preserving association between a NuBagz account and a network signal.

    NuBagz never stores the raw client IP here. ``ip_hash`` is an HMAC generated
    with the dedicated ABUSE_SIGNAL_KEY and the observation is bucketed by day so
    old associations can age out of Trust analysis naturally.
    """

    __tablename__ = "network_observations"
    __table_args__ = (
        UniqueConstraint("user_id", "ip_hash", "day_bucket", name="uq_user_network_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    day_bucket: Mapped[str] = mapped_column(String(10), index=True)
    request_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class SecurityEvent(Base):
    """Append-only anti-abuse event evidence.

    This table records security outcomes such as throttling and successful human
    verification. It deliberately stores only the keyed network hash, never a raw
    IP address, and does not itself change account state or Trust level.
    """

    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    route_group: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
