from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..economy_models import CampaignFunding
from ..models import Campaign, Enrollment, Project, User
from ..trust_models import ProjectTrustEvidence

router = APIRouter(prefix="/api/trust", tags=["trust"])
SCORE_VERSION = "3.0"
PUBLIC_PROJECT_STATUSES = {"LIVE", "APPROVED"}


class TrustEvidenceIn(BaseModel):
    project_id: int
    contract_address: str | None = Field(default=None, max_length=255)
    token_launch_date: str | None = Field(default=None, max_length=32)
    docs_url: str | None = Field(default=None, max_length=500)
    socials_url: str | None = Field(default=None, max_length=500)
    team_url: str | None = Field(default=None, max_length=500)
    contract_source_verified: bool = False
    dangerous_permissions_absent: bool = False
    liquidity_verified: bool = False
    holder_distribution_verified: bool = False
    team_verified: bool = False
    docs_verified: bool = False
    socials_verified: bool = False


class TrustVerifyIn(BaseModel):
    status: str
    notes: str | None = Field(default=None, max_length=2000)


def _days_since(value: datetime) -> int:
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return max(0, (datetime.now(UTC) - value).days)


def _token_age_days(raw: str | None) -> int:
    if not raw:
        return 0
    try:
        launched = date.fromisoformat(raw[:10])
        return max(0, (datetime.now(UTC).date() - launched).days)
    except ValueError:
        return 0


def evidence_payload(evidence: ProjectTrustEvidence | None):
    if not evidence:
        return {
            "status": "NOT_SUBMITTED",
            "contract_address": None,
            "token_launch_date": None,
            "docs_url": None,
            "socials_url": None,
            "team_url": None,
            "verified_at": None,
        }
    return {
        "id": evidence.id,
        "status": evidence.verification_status,
        "contract_address": evidence.contract_address,
        "token_launch_date": evidence.token_launch_date,
        "docs_url": evidence.docs_url,
        "socials_url": evidence.socials_url,
        "team_url": evidence.team_url,
        "contract_source_verified": evidence.contract_source_verified,
        "dangerous_permissions_absent": evidence.dangerous_permissions_absent,
        "liquidity_verified": evidence.liquidity_verified,
        "holder_distribution_verified": evidence.holder_distribution_verified,
        "team_verified": evidence.team_verified,
        "docs_verified": evidence.docs_verified,
        "socials_verified": evidence.socials_verified,
        "verification_notes": evidence.verification_notes,
        "verified_at": evidence.verified_at.isoformat() if evidence.verified_at else None,
    }


def project_trust(project: Project, db: Session):
    campaigns = db.query(Campaign).filter(Campaign.project_id == project.id).all()
    campaign_ids = [campaign.id for campaign in campaigns]
    evidence = db.query(ProjectTrustEvidence).filter(
        ProjectTrustEvidence.project_id == project.id
    ).first()
    evidence_verified = bool(evidence and evidence.verification_status == "VERIFIED")

    fully_funded = 0
    for campaign in campaigns:
        funding = db.query(CampaignFunding).filter(
            CampaignFunding.campaign_id == campaign.id,
            CampaignFunding.status == "VERIFIED",
        ).first()
        required = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.max_users)
        if funding and Decimal(funding.verified_amount) >= required:
            fully_funded += 1
    funding_ratio = Decimal(fully_funded) / Decimal(len(campaigns)) if campaigns else Decimal("0")
    funding_points = min(20, int(funding_ratio * Decimal("20")))

    if campaign_ids:
        enrollments = db.query(func.count(Enrollment.id)).filter(
            Enrollment.campaign_id.in_(campaign_ids)
        ).scalar() or 0
        completions = db.query(func.count(Enrollment.id)).filter(
            Enrollment.campaign_id.in_(campaign_ids),
            Enrollment.status == "COMPLETED",
        ).scalar() or 0
    else:
        enrollments = completions = 0
    completion_rate = Decimal(completions) / Decimal(enrollments) if enrollments else Decimal("0")
    completion_points = min(15, int(completion_rate * Decimal("15")))

    transparency_points = (
        (4 if project.website else 0)
        + (3 if project.treasury_address else 0)
        + (3 if evidence_verified and evidence and evidence.docs_verified and evidence.socials_verified else 0)
    )
    project_age_days = _days_since(project.created_at)
    token_age_days = _token_age_days(evidence.token_launch_date if evidence else None)
    history_points = min(10, project_age_days // 30)
    maturity_points = min(5, project_age_days // 60) + min(5, token_age_days // 90)

    contract_points = market_points = identity_points = 0
    if evidence_verified and evidence:
        if evidence.contract_address:
            contract_points += 3
        if evidence.contract_source_verified:
            contract_points += 4
        if evidence.dangerous_permissions_absent:
            contract_points += 8
        if evidence.liquidity_verified:
            market_points += 5
        if evidence.holder_distribution_verified:
            market_points += 5
        if evidence.team_verified:
            identity_points += 4
        if evidence.docs_verified:
            identity_points += 3
        if evidence.socials_verified:
            identity_points += 3

    factors = {
        "project_history": history_points,
        "verified_funding": funding_points,
        "completion_quality": completion_points,
        "transparency": transparency_points,
        "maturity": maturity_points,
        "contract_safety": contract_points,
        "market_structure": market_points,
        "identity_community": identity_points,
    }
    score = min(100, sum(factors.values()))
    level = "LOW SIGNAL"
    if score >= 80:
        level = "STRONG"
    elif score >= 60:
        level = "ESTABLISHED"
    elif score >= 40:
        level = "DEVELOPING"
    elif score >= 20:
        level = "EARLY"

    return {
        "project_id": project.id,
        "name": project.name,
        "symbol": project.symbol,
        "score": score,
        "level": level,
        "factors": factors,
        "metrics": {
            "campaigns": len(campaigns),
            "verified_funded_campaigns": fully_funded,
            "participants": int(enrollments),
            "completions": int(completions),
            "completion_rate_pct": str(completion_rate * Decimal("100")),
            "project_age_days": project_age_days,
            "token_age_days": token_age_days,
        },
        "project_profile": {
            "website": project.website,
            "treasury_address": project.treasury_address,
            "chain": project.chain,
            "logo_url": project.logo_url,
        },
        "evidence": evidence_payload(evidence),
        "score_version": SCORE_VERSION,
        "calculated_at": datetime.now(UTC).isoformat(),
        "disclaimer": "NuBagz Trust Score is a risk-context signal based on verified evidence and observed NuBagz activity. It is not an endorsement, audit, guarantee, or investment recommendation.",
    }


@router.get("/projects")
def trust_projects(
    q: str | None = Query(default=None, max_length=255),
    db: Session = Depends(get_db),
):
    query = db.query(Project).outerjoin(
        ProjectTrustEvidence,
        ProjectTrustEvidence.project_id == Project.id,
    ).filter(Project.status.in_(PUBLIC_PROJECT_STATUSES))
    term = (q or "").strip()
    if term:
        pattern = f"%{term}%"
        query = query.filter(or_(
            Project.name.ilike(pattern),
            Project.symbol.ilike(pattern),
            Project.chain.ilike(pattern),
            ProjectTrustEvidence.contract_address.ilike(pattern),
        ))
    projects = query.order_by(Project.created_at.desc()).all()
    return sorted(
        [project_trust(project, db) for project in projects],
        key=lambda item: item["score"],
        reverse=True,
    )


@router.get("/projects/{project_id}")
def trust_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project or project.status in {"SUSPENDED", "ARCHIVED"}:
        raise HTTPException(404, "Project not found")
    return project_trust(project, db)


@router.post("/evidence")
def submit_evidence(
    data: TrustEvidenceIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = db.get(Project, data.project_id)
    if not project or (project.owner_id != user.id and user.role != "ADMIN"):
        raise HTTPException(403, "You do not manage this project")
    if data.token_launch_date:
        try:
            launched = date.fromisoformat(data.token_launch_date[:10])
            if launched > datetime.now(UTC).date():
                raise ValueError
        except ValueError:
            raise HTTPException(400, "Token launch date must be a valid past date in YYYY-MM-DD format")
    if data.team_verified and not (data.team_url or "").strip():
        raise HTTPException(400, "Add a team/founder evidence URL before submitting team identity evidence")

    evidence = db.query(ProjectTrustEvidence).filter(
        ProjectTrustEvidence.project_id == project.id
    ).first()
    if not evidence:
        evidence = ProjectTrustEvidence(project_id=project.id, submitted_by_id=user.id)
        db.add(evidence)
    for key, value in data.model_dump(exclude={"project_id"}).items():
        setattr(evidence, key, value)
    evidence.submitted_by_id = user.id
    evidence.verification_status = "SUBMITTED"
    evidence.verification_notes = None
    evidence.verified_by_id = None
    evidence.verified_at = None
    db.commit()
    db.refresh(evidence)
    return {
        "project_id": project.id,
        "evidence": evidence_payload(evidence),
        "score": project_trust(project, db)["score"],
    }


@router.get("/admin/evidence")
def admin_evidence(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    rows = db.query(ProjectTrustEvidence).order_by(ProjectTrustEvidence.updated_at.desc()).all()
    return [
        {
            "project_id": evidence.project_id,
            "project_name": db.get(Project, evidence.project_id).name,
            "evidence": evidence_payload(evidence),
        }
        for evidence in rows
    ]


@router.post("/admin/evidence/{project_id}/verify")
def verify_evidence(
    project_id: int,
    data: TrustVerifyIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    evidence = db.query(ProjectTrustEvidence).filter(
        ProjectTrustEvidence.project_id == project_id
    ).first()
    if not evidence:
        raise HTTPException(404, "Trust evidence not found")
    status = data.status.upper()
    if status not in {"VERIFIED", "REJECTED"}:
        raise HTTPException(400, "Evidence decision must be VERIFIED or REJECTED")
    evidence.verification_status = status
    evidence.verification_notes = data.notes
    evidence.verified_by_id = admin.id
    evidence.verified_at = datetime.now(UTC) if status == "VERIFIED" else None
    db.commit()
    project = db.get(Project, project_id)
    return {
        "project_id": project_id,
        "evidence": evidence_payload(evidence),
        "score": project_trust(project, db)["score"] if project else None,
    }
