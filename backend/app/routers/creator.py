from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..challenge_models import Challenge
from ..db import get_db
from ..deps import get_current_user
from ..economy_models import CampaignAccessRule, CampaignFunding
from ..integration_models import GasSponsorshipPolicy
from ..models import Campaign, Project, User
from ..schemas import CampaignCreate, ProjectCreate
from ..trust_models import ProjectTrustEvidence
from ..utils import slugify

router = APIRouter(prefix="/api/creator", tags=["creator"])

GAS_NATIVE = {
    "avalanche": "AVAX",
    "ethereum": "ETH",
    "base": "ETH",
    "arbitrum": "ETH",
    "polygon": "POL",
}


class ProjectTrustDraft(BaseModel):
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

    @model_validator(mode="after")
    def validate_trust_draft(self):
        if self.token_launch_date:
            try:
                launched = date.fromisoformat(self.token_launch_date[:10])
            except ValueError as exc:
                raise ValueError("Token launch date must use YYYY-MM-DD") from exc
            if launched > datetime.now(UTC).date():
                raise ValueError("Token launch date cannot be in the future")
        return self

    def has_content(self) -> bool:
        return any(value not in {None, "", False} for value in self.model_dump().values())


class RewardFundingDraft(BaseModel):
    amount: Decimal = Field(gt=0)
    tx_hash: str | None = Field(default=None, max_length=255)


class CreatorLaunchIn(BaseModel):
    project: ProjectCreate
    bag: CampaignCreate
    trust: ProjectTrustDraft | None = None
    reward_funding: RewardFundingDraft | None = None
    min_bag_score: int = Field(default=0, ge=0, le=1000)


class CreatorLaunchOut(BaseModel):
    project_id: int
    project_slug: str
    project_status: str
    campaign_id: int
    campaign_status: str
    trust_status: str
    reward_funding_status: str
    gas_policies_created: int
    message: str


def _next_slug(db: Session, name: str) -> str:
    base = slugify(name)
    slug = base
    suffix = 2
    while db.query(Project.id).filter(Project.slug == slug).first():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _create_gas_policy(
    db: Session,
    *,
    challenge: Challenge,
    project: Project,
    user: User,
    gas,
) -> GasSponsorshipPolicy:
    chain_key = gas.chain.strip().lower()
    if chain_key not in GAS_NATIVE:
        raise HTTPException(400, "Gas Pass currently supports Avalanche, Ethereum, Base, Arbitrum and Polygon")
    policy = GasSponsorshipPolicy(
        challenge_id=challenge.id,
        project_id=project.id,
        created_by_id=user.id,
        chain=gas.chain.strip().title(),
        native_asset=GAS_NATIVE[chain_key],
        max_native_per_claim=gas.max_native_per_claim,
        max_unique_users=gas.max_unique_users,
        max_claims=gas.max_claims,
        max_claims_per_wallet=gas.max_claims_per_wallet,
        funded_amount=gas.funded_amount,
        funding_reference=gas.funding_reference.strip(),
        starts_at=gas.starts_at,
        ends_at=gas.ends_at,
        funding_status="DECLARED",
        status="FUNDING_PENDING",
    )
    db.add(policy)
    return policy


@router.post("/launch", response_model=CreatorLaunchOut)
def launch_project_and_first_bag(
    data: CreatorLaunchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a project, Trust draft, first Bag and unified Bag Work atomically."""
    try:
        project = Project(
            owner_id=user.id,
            slug=_next_slug(db, data.project.name),
            status="LIVE",
            **data.project.model_dump(),
        )
        db.add(project)
        db.flush()

        if user.role == "USER":
            user.role = "CREATOR"

        trust_status = "NOT_SUBMITTED"
        if data.trust and data.trust.has_content():
            evidence = ProjectTrustEvidence(
                project_id=project.id,
                submitted_by_id=user.id,
                verification_status="SUBMITTED",
                **data.trust.model_dump(),
            )
            db.add(evidence)
            trust_status = "SUBMITTED"

        bag_values = data.bag.model_dump(exclude={"project_id", "missions", "challenges"})
        campaign = Campaign(project_id=project.id, status="DRAFT", **bag_values)
        db.add(campaign)
        db.flush()

        gas_policies_created = 0
        for index, challenge_data in enumerate(data.bag.challenges):
            challenge = Challenge(
                campaign_id=campaign.id,
                position=index,
                **challenge_data.model_dump(exclude={"gas_sponsorship"}),
            )
            db.add(challenge)
            db.flush()
            gas = challenge_data.gas_sponsorship
            if gas and gas.enabled:
                _create_gas_policy(db, challenge=challenge, project=project, user=user, gas=gas)
                gas_policies_created += 1

        if data.min_bag_score > 0:
            db.add(CampaignAccessRule(
                campaign_id=campaign.id,
                min_bag_score=data.min_bag_score,
                updated_by_id=user.id,
            ))

        reward_funding_status = "UNFUNDED"
        if data.reward_funding:
            db.add(CampaignFunding(
                campaign_id=campaign.id,
                declared_amount=data.reward_funding.amount,
                verified_amount=Decimal("0"),
                tx_hash=data.reward_funding.tx_hash,
                status="DECLARED",
            ))
            reward_funding_status = "DECLARED"

        db.commit()
        db.refresh(project)
        db.refresh(campaign)
        return CreatorLaunchOut(
            project_id=project.id,
            project_slug=project.slug,
            project_status=project.status,
            campaign_id=campaign.id,
            campaign_status=campaign.status,
            trust_status=trust_status,
            reward_funding_status=reward_funding_status,
            gas_policies_created=gas_policies_created,
            message=(
                "Project published. First Bag saved as DRAFT. Once its full reward obligation "
                "is independently verified it will become live in Bag Work automatically."
            ),
        )
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Project launch conflicted with an existing record") from exc
    except Exception:
        db.rollback()
        raise
