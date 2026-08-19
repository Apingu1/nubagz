from datetime import datetime, UTC
from decimal import Decimal
from sqlalchemy import String, Integer, DateTime, ForeignKey, Numeric, Text, Boolean, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def now():
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(24), default="USER", index=True)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    bag_score: Mapped[int] = mapped_column(Integer, default=100)
    streak_days: Mapped[int] = mapped_column(Integer, default=0)
    referral_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    referred_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    wallet_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wallet_chain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    projects = relationship("Project", back_populates="owner")
    ledger_entries = relationship("LedgerEntry", back_populates="user")


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(24))
    description: Mapped[str] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chain: Mapped[str] = mapped_column(String(32), default="Avalanche")
    logo_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    treasury_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    owner = relationship("User", back_populates="projects")
    campaigns = relationship("Campaign", back_populates="project", cascade="all, delete-orphan")


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), default="DISCOVER")
    difficulty: Mapped[str] = mapped_column(String(20), default="EASY")
    reward_asset: Mapped[str] = mapped_column(String(24))
    funding_type: Mapped[str] = mapped_column(String(24), default="TOKEN")
    token_allocation: Mapped[Decimal] = mapped_column(Numeric(36, 8), default=0)
    gross_reward_per_user: Mapped[Decimal] = mapped_column(Numeric(36, 8), default=0)
    user_share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("80"))
    nubagz_share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("15"))
    referral_share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("5"))
    max_users: Mapped[int] = mapped_column(Integer, default=1000)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    estimated_value_gbp: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    project = relationship("Project", back_populates="campaigns")
    missions = relationship("Mission", back_populates="campaign", cascade="all, delete-orphan", order_by="Mission.position")
    enrollments = relationship("Enrollment", back_populates="campaign")


class Mission(Base):
    __tablename__ = "missions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    mission_type: Mapped[str] = mapped_column(String(32), default="LEARN")
    verification_type: Mapped[str] = mapped_column(String(32), default="SELF_ATTEST")
    target_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    quiz_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    quiz_options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    quiz_answer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    xp_reward: Mapped[int] = mapped_column(Integer, default=50)
    position: Mapped[int] = mapped_column(Integer, default=0)

    campaign = relationship("Campaign", back_populates="missions")


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("user_id", "campaign_id", name="uq_user_campaign"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE")
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    earned_amount: Mapped[Decimal] = mapped_column(Numeric(36, 8), default=0)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    campaign = relationship("Campaign", back_populates="enrollments")


class MissionCompletion(Base):
    __tablename__ = "mission_completions"
    __table_args__ = (UniqueConstraint("user_id", "mission_id", name="uq_user_mission"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id"), index=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True, index=True)
    asset_symbol: Mapped[str] = mapped_column(String(24), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 8))
    entry_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="AVAILABLE")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    user = relationship("User", back_populates="ledger_entries")


class Withdrawal(Base):
    __tablename__ = "withdrawals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    asset_symbol: Mapped[str] = mapped_column(String(24))
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 8))
    chain: Mapped[str] = mapped_column(String(32))
    wallet_address: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    tx_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class FraudFlag(Base):
    __tablename__ = "fraud_flags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(24), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
