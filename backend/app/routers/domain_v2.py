from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..challenge_models import Challenge, ChallengeCompletion
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..economy_models import CampaignAccessRule, CampaignFunding
from ..models import Campaign, Enrollment, Project, User
from ..schemas import CampaignCreate, ChallengeCreate
from ..x_verifier import make_x_proof_code
from .campaigns import create_campaign, funding_available, pause_campaign, publish_campaign, serialize_campaign
from .challenges import _gas_summary
from .funding import FundingDeclareIn, FundingVerifyIn, declare_funding, verify_funding
from .risk import evaluate_user
from .watchbag import unwatch as legacy_unwatch
from .watchbag import watch as legacy_watch
from .watchbag import watch_status as legacy_watch_status

router = APIRouter(tags=["domain-v2"])
PUBLIC_PROJECT_STATUSES = {"LIVE", "APPROVED"}
VERIFIED_STATUSES = {"VERIFIED", "APPROVED"}


class ProjectChallengeCreate(BaseModel):
    """Phase-1 canonical create shape.

    The database still uses Campaign as a compatibility reward/funding container until
    the Phase-3 Challenge migration. New V2 creation is intentionally one Challenge
    per compatibility container so the public domain is already Project -> Challenge.
    """

    challenge: ChallengeCreate
    reward_asset: str = Field(min_length=1, max_length=24)
    token_allocation: Decimal = Field(gt=0)
    gross_reward_per_user: Decimal = Field(gt=0)
    user_share_pct: Decimal = Decimal("80")
    nubagz_share_pct: Decimal = Decimal("15")
    referral_share_pct: Decimal = Decimal("5")
    max_users: int = Field(gt=0, le=1_000_000)
    estimated_value_gbp: Decimal | None = None
    reward_funding_reference: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_v2_challenge(self):
        if len(self.challenge.description.strip()) < 20:
            raise ValueError("Challenge description must be at least 20 characters")
        if self.user_share_pct + self.nubagz_share_pct + self.referral_share_pct != Decimal("100"):
            raise ValueError("Reward shares must total 100%")
        if self.gross_reward_per_user * self.max_users > self.token_allocation:
            raise ValueError("Reward allocation must cover the maximum Challenge liability")
        return self


def _funding_for(db: Session, campaign_id: int) -> CampaignFunding | None:
    return db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign_id).first()


def _challenge_context(db: Session, challenge_id: int):
    challenge = db.get(Challenge, challenge_id)
    campaign = db.get(Campaign, challenge.campaign_id) if challenge else None
    project = db.get(Project, campaign.project_id) if campaign else None
    if not challenge or not campaign or not project:
        raise HTTPException(404, "Challenge not found")
    return challenge, campaign, project


def _require_challenge_manager(db: Session, challenge_id: int, user: User):
    challenge, campaign, project = _challenge_context(db, challenge_id)
    if project.owner_id != user.id and user.role != "ADMIN":
        raise HTTPException(404, "Challenge not found")
    return challenge, campaign, project


def _active_requirement_count(db: Session, campaign_id: int) -> int:
    return int(db.query(func.count(Challenge.id)).filter(
        Challenge.campaign_id == campaign_id,
        Challenge.status == "ACTIVE",
    ).scalar() or 0)


def _canonical_from_campaign(campaign, challenge, funding: CampaignFunding | None = None, linked_requirement_count: int = 1) -> dict:
    gross = Decimal(campaign.gross_reward_per_user)
    user_amount = gross * Decimal(campaign.user_share_pct) / Decimal("100")
    required = gross * Decimal(campaign.max_users)
    verified_amount = Decimal(funding.verified_amount) if funding else Decimal("0")
    fully_funded = bool(funding and funding.status == "VERIFIED" and verified_amount >= required)
    return {
        "id": challenge.id,
        "project_id": campaign.project_id,
        "title": challenge.title,
        "description": challenge.description,
        "category": challenge.category,
        "provider": challenge.provider,
        "action": challenge.action,
        "verification_type": challenge.verification_type,
        "target_url": challenge.target_url,
        "target_id": challenge.target_id,
        "config": challenge.config,
        "xp_reward_compat": challenge.xp_reward,
        "position": challenge.position,
        "status": challenge.status,
        "created_at": challenge.created_at,
        "reward_asset": campaign.reward_asset,
        "gross_reward_per_user": str(gross),
        "user_reward": str(user_amount),
        "user_share_pct": str(campaign.user_share_pct),
        "nubagz_share_pct": str(campaign.nubagz_share_pct),
        "referral_share_pct": str(campaign.referral_share_pct),
        "max_users": campaign.max_users,
        "challenge_status": campaign.status,
        "funding_status": funding.status if funding else "UNFUNDED",
        "fully_funded": fully_funded,
        "discoverable": bool(campaign.status == "LIVE" and challenge.status == "ACTIVE" and fully_funded),
        "compatibility_grouped": linked_requirement_count > 1,
        "linked_requirement_count": linked_requirement_count,
    }


def _canonical_funding(db: Session, challenge: Challenge, campaign: Campaign, project: Project) -> dict:
    funding = _funding_for(db, campaign.id)
    required = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.max_users)
    declared = Decimal(funding.declared_amount) if funding else Decimal("0")
    verified = Decimal(funding.verified_amount) if funding else Decimal("0")
    fully_funded = bool(funding and funding.status == "VERIFIED" and verified >= required)
    linked_count = _active_requirement_count(db, campaign.id)
    return {
        "challenge_id": challenge.id,
        "project_id": project.id,
        "asset": campaign.reward_asset,
        "required_amount": str(required),
        "declared_amount": str(declared),
        "verified_amount": str(verified),
        "status": funding.status if funding else "UNFUNDED",
        "tx_hash": funding.tx_hash if funding else None,
        "fully_funded": fully_funded,
        "challenge_status": campaign.status,
        "discoverable": bool(
            campaign.status == "LIVE"
            and challenge.status == "ACTIVE"
            and project.status in PUBLIC_PROJECT_STATUSES
            and fully_funded
        ),
        "compatibility_grouped": linked_count > 1,
        "linked_requirement_count": linked_count,
    }


@router.get("/api/projects/{project_id}/challenges")
def project_challenges(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    owner_view = project.owner_id == user.id or user.role == "ADMIN"
    if not owner_view and project.status not in PUBLIC_PROJECT_STATUSES:
        raise HTTPException(404, "Project not found")

    q = db.query(Campaign).filter(Campaign.project_id == project_id)
    if not owner_view:
        q = q.filter(Campaign.status == "LIVE")
    rows = []
    for campaign in q.order_by(Campaign.created_at.desc()).all():
        serialized = serialize_campaign(campaign, db)
        funding = _funding_for(db, campaign.id)
        linked_count = len([row for row in serialized.challenges if row.status == "ACTIVE"])
        for challenge in serialized.challenges:
            if not owner_view and challenge.status != "ACTIVE":
                continue
            rows.append(_canonical_from_campaign(serialized, challenge, funding, linked_count))
    return rows


@router.post("/api/projects/{project_id}/challenges")
def create_project_challenge(
    project_id: int,
    data: ProjectChallengeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project or project.owner_id != user.id:
        raise HTTPException(404, "Project not found")
    if project.status not in PUBLIC_PROJECT_STATUSES:
        raise HTTPException(409, "Suspended or archived projects cannot create Challenges")

    legacy = CampaignCreate(
        project_id=project_id,
        title=data.challenge.title,
        description=data.challenge.description,
        category="DISCOVER",
        difficulty="EASY",
        reward_asset=data.reward_asset,
        funding_type="TOKEN",
        token_allocation=data.token_allocation,
        gross_reward_per_user=data.gross_reward_per_user,
        user_share_pct=data.user_share_pct,
        nubagz_share_pct=data.nubagz_share_pct,
        referral_share_pct=data.referral_share_pct,
        max_users=data.max_users,
        estimated_value_gbp=data.estimated_value_gbp,
        missions=[],
        challenges=[data.challenge],
    )
    created = create_campaign(legacy, db, user)
    if len(created.challenges) != 1:
        raise HTTPException(500, "V2 Challenge creation did not produce a one-to-one Challenge record")

    funding = None
    reference = (data.reward_funding_reference or "").strip()
    if reference:
        declare_funding(
            created.id,
            FundingDeclareIn(amount=data.token_allocation, tx_hash=reference),
            db,
            user,
        )
        funding = _funding_for(db, created.id)
    return _canonical_from_campaign(created, created.challenges[0], funding, 1)


@router.get("/api/challenges/{challenge_id}")
def canonical_challenge(
    challenge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge, campaign, project = _challenge_context(db, challenge_id)
    if (
        challenge.status != "ACTIVE"
        or campaign.status != "LIVE"
        or project.status not in PUBLIC_PROJECT_STATUSES
    ):
        raise HTTPException(404, "Challenge not found")

    completion = db.query(ChallengeCompletion).filter(
        ChallengeCompletion.user_id == user.id,
        ChallengeCompletion.challenge_id == challenge.id,
    ).first()
    enrollment = db.query(Enrollment).filter(
        Enrollment.user_id == user.id,
        Enrollment.campaign_id == campaign.id,
    ).first()
    active_count = _active_requirement_count(db, campaign.id)
    completed_count = db.query(func.count(ChallengeCompletion.id)).join(
        Challenge, Challenge.id == ChallengeCompletion.challenge_id,
    ).filter(
        ChallengeCompletion.user_id == user.id,
        Challenge.campaign_id == campaign.id,
        ChallengeCompletion.status.in_(VERIFIED_STATUSES),
    ).scalar() or 0
    enrolled_count = db.query(func.count(Enrollment.id)).filter(
        Enrollment.campaign_id == campaign.id,
    ).scalar() or 0
    access = db.query(CampaignAccessRule).filter(CampaignAccessRule.campaign_id == campaign.id).first()
    gross = Decimal(campaign.gross_reward_per_user)
    user_amount = gross * Decimal(campaign.user_share_pct) / Decimal("100")
    social_auto = challenge.category == "SOCIAL" and challenge.provider == "X" and challenge.verification_type == "AUTO"

    return {
        "id": challenge.id,
        "project_id": project.id,
        "project_name": project.name,
        "project_symbol": project.symbol,
        "project_chain": project.chain,
        "title": challenge.title,
        "description": challenge.description,
        "category": challenge.category,
        "provider": challenge.provider,
        "action": challenge.action,
        "verification_type": challenge.verification_type,
        "target_url": challenge.target_url,
        "target_id": challenge.target_id,
        "config": {key: value for key, value in (challenge.config or {}).items() if key != "answer"},
        "proof_code": make_x_proof_code(user.id, challenge.id) if social_auto else None,
        "xp_reward_compat": challenge.xp_reward,
        "completion_status": completion.status if completion else None,
        "joined": bool(enrollment),
        "enrollment_status": enrollment.status if enrollment else None,
        "compatibility_grouped": active_count > 1,
        "linked_requirement_count": active_count,
        "linked_completed_count": completed_count,
        "compatibility_group_path": f"/app/bagz/{campaign.id}?challenge={challenge.id}" if active_count > 1 else None,
        "available_spots": max(0, campaign.max_users - enrolled_count),
        "minimum_points_compat": access.min_bag_score if access else 0,
        "project_reward": {
            "asset": campaign.reward_asset,
            "gross_amount": str(gross),
            "user_amount": str(user_amount),
            "user_share_pct": str(campaign.user_share_pct),
            "nubagz_share_pct": str(campaign.nubagz_share_pct),
            "referral_share_pct": str(campaign.referral_share_pct),
        },
        "gas_pass": _gas_summary(db, challenge),
    }


@router.post("/api/challenges/{challenge_id}/join")
def join_challenge(
    challenge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge, campaign, project = _challenge_context(db, challenge_id)
    if (
        challenge.status != "ACTIVE"
        or campaign.status != "LIVE"
        or project.status not in PUBLIC_PROJECT_STATUSES
    ):
        raise HTTPException(404, "Challenge is not live")

    existing = db.query(Enrollment).filter(
        Enrollment.user_id == user.id,
        Enrollment.campaign_id == campaign.id,
    ).first()
    if existing:
        return {"ok": True, "joined": True, "status": existing.status}
    if not funding_available(db, campaign, Decimal(campaign.gross_reward_per_user)):
        raise HTTPException(409, "This Challenge is temporarily unavailable because verified reward inventory is exhausted")
    trust = evaluate_user(db, user)
    if trust.trust_level == "RESTRICTED":
        raise HTTPException(403, "This account is restricted from new reward opportunities pending trust review")
    access = db.query(CampaignAccessRule).filter(CampaignAccessRule.campaign_id == campaign.id).first()
    if access and user.bag_score < access.min_bag_score:
        raise HTTPException(403, f"{access.min_bag_score}+ Points required for this legacy access rule")
    enrolled_count = db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id == campaign.id).scalar() or 0
    if enrolled_count >= campaign.max_users:
        raise HTTPException(409, "This Challenge is full")

    enrollment = Enrollment(user_id=user.id, campaign_id=campaign.id)
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return {"ok": True, "joined": True, "status": enrollment.status}


@router.get("/api/challenges/{challenge_id}/funding")
def challenge_funding(
    challenge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge, campaign, project = _require_challenge_manager(db, challenge_id, user)
    return _canonical_funding(db, challenge, campaign, project)


@router.post("/api/challenges/{challenge_id}/funding/declare")
def declare_challenge_funding(
    challenge_id: int,
    data: FundingDeclareIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge, campaign, project = _require_challenge_manager(db, challenge_id, user)
    declare_funding(campaign.id, data, db, user)
    return _canonical_funding(db, challenge, campaign, project)


@router.post("/api/challenges/{challenge_id}/funding/verify")
def verify_challenge_funding(
    challenge_id: int,
    data: FundingVerifyIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    challenge, campaign, project = _challenge_context(db, challenge_id)
    verify_funding(campaign.id, data, db, admin)
    db.refresh(campaign)
    return _canonical_funding(db, challenge, campaign, project)


@router.post("/api/challenges/{challenge_id}/pause")
def pause_challenge(
    challenge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge, campaign, _ = _require_challenge_manager(db, challenge_id, user)
    grouped = _active_requirement_count(db, campaign.id) > 1
    if grouped:
        raise HTTPException(409, "Pre-V2 grouped records must be managed through their compatibility record until Phase 3")
    result = pause_campaign(campaign.id, db, user)
    return {"ok": True, "challenge_id": challenge.id, "status": result["status"]}


@router.post("/api/challenges/{challenge_id}/resume")
def resume_challenge(
    challenge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge, campaign, _ = _require_challenge_manager(db, challenge_id, user)
    grouped = _active_requirement_count(db, campaign.id) > 1
    if grouped:
        raise HTTPException(409, "Pre-V2 grouped records must be managed through their compatibility record until Phase 3")
    result = publish_campaign(campaign.id, db, user)
    return {"ok": True, "challenge_id": challenge.id, "status": result["status"]}


@router.get("/api/challenges/{challenge_id}/watch")
def challenge_watch_status(
    challenge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge, campaign, _ = _challenge_context(db, challenge_id)
    out = legacy_watch_status(campaign.id, db, user)
    return {
        "challenge_id": challenge.id,
        "watched": out["watched"],
        "watchable": out["watchable"],
        "watchability_reason": out["watchability_reason"],
        "remaining_reward_inventory": out["remaining_reward_inventory"],
        "reservation": False,
    }


@router.post("/api/challenges/{challenge_id}/watch")
def watch_challenge(
    challenge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge, campaign, _ = _challenge_context(db, challenge_id)
    out = legacy_watch(campaign.id, db, user)
    return {
        "challenge_id": challenge.id,
        "watched": True,
        "watchable": out["watchable"],
        "watchability_reason": out["watchability_reason"],
        "remaining_reward_inventory": out["remaining_reward_inventory"],
        "reservation": False,
    }


@router.delete("/api/challenges/{challenge_id}/watch")
def unwatch_challenge(
    challenge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge, campaign, _ = _challenge_context(db, challenge_id)
    legacy_unwatch(campaign.id, db, user)
    return {"ok": True, "challenge_id": challenge.id, "watched": False}
