from datetime import datetime, UTC
from decimal import Decimal
from sqlalchemy import String, Integer, DateTime, ForeignKey, Numeric, Text, Boolean, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def now():
    return datetime.now(UTC)


ACCOUNT_STATES = {"ACTIVE", "UNDER_REVIEW", "RESTRICTED", "SUSPENDED", "DISQUALIFIED"}


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
    # Compatibility mirror of the selected reward destination. This is not proof
    # of wallet ownership and must never satisfy interactive-wallet requirements.
    wallet_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wallet_chain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Retained during the V2 migration for compatibility with legacy queries.
    # account_state is the authoritative V2 account lifecycle field.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    account_state: Mapped[str] = mapped_column(String(24), default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    projects = relationship("Project", back_populates="owner")
    ledger_entries = relationship("LedgerEntry", back_populates="user")
    wallet_connections = relationship("WalletConnection", back_populates="user", cascade="all, delete-orphan")
    payout_addresses = relationship("PayoutAddress", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    auth_method: Mapped[str] = mapped_column(String(24), default="PASSWORD")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user = relationship("User", back_populates="sessions")


class WalletConnection(Base):
    __tablename__ = "wallet_connections"
    __table_args__ = (UniqueConstraint("user_id", "address", name="uq_user_wallet_address"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    address: Mapped[str] = mapped_column(String(255), index=True)
    chain_type: Mapped[str] = mapped_column(String(24), default="ethereum")
    chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wallet_client_type: Mapped[str] = mapped_column(String(64), default="unknown")
    connector_type: Mapped[str] = mapped_column(String(64), default="unknown")
    wallet_type: Mapped[str] = mapped_column(String(24), default="EXTERNAL")
    # is_primary remains the selected reward destination compatibility flag.
    # is_primary_interactive independently selects the preferred verified signer.
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_primary_interactive: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_connected_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    user = relationship("User", back_populates="wallet_connections")


class WalletChallenge(Base):
    __tablename__ = "wallet_challenges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    address: Mapped[str] = mapped_column(String(255), index=True)
    nonce: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    message: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PayoutAddress(Base):
    __tablename__ = "payout_addresses"
    __table_args__ = (UniqueConstraint("user_id", "chain", "address", name="uq_user_payout_address"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    address: Mapped[str] = mapped_column(String(255), index=True)
    chain: Mapped[str] = mapped_column(String(32), default="Avalanche")
    label: Mapped[str] = mapped_column(String(80), default="Reward address")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    verification_status: Mapped[str] = mapped_column(String(24), default="UNVERIFIED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    user = relationship("User", back_populates="payout_addresses")


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
    status: Mapped[str] = mapped_column(String(24), default="LIVE", index=True)
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
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", index=True)
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
