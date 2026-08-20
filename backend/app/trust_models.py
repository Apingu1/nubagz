from datetime import datetime, UTC
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.now(UTC)


class ProjectTrustEvidence(Base):
    __tablename__ = "project_trust_evidence"
    __table_args__ = (UniqueConstraint("project_id", name="uq_project_trust_evidence_project"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    submitted_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    contract_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_launch_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    docs_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    socials_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    contract_source_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    dangerous_permissions_absent: Mapped[bool] = mapped_column(Boolean, default=False)
    liquidity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    holder_distribution_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    team_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    docs_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    socials_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    verification_status: Mapped[str] = mapped_column(String(24), default="SUBMITTED", index=True)
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
