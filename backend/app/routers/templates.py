import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..challenge_models import Challenge
from ..db import get_db
from ..deps import get_current_user
from ..engagement_models import CampaignTemplate
from ..models import User, Project, Campaign
from ..schemas import CampaignCreate, ChallengeCreate

router = APIRouter(prefix="/api/templates", tags=["campaign-templates"])
PUBLIC_PROJECT_STATUSES = {"LIVE", "APPROVED"}

# The database column is still named mission_blueprint for backwards-compatible
# storage, but all new template content is the unified Challenge architecture.
SYSTEM_TEMPLATES = [
    {
        "name": "Learn → Prove → Claim",
        "description": "A beginner onboarding flow that teaches the project, collects evidence of participation and finishes with a funded completion.",
        "category": "LEARN",
        "difficulty": "EASY",
        "max_users": 1000,
        "challenges": [
            {"title": "Meet the project", "description": "Read the project briefing and understand the core utility.", "category": "LEARN", "verification_type": "PROJECT_REVIEW", "xp_reward": 60},
            {"title": "Show what you learned", "description": "Provide a short proof link or evidence note showing that you completed the learning step.", "category": "LEARN", "verification_type": "PROJECT_REVIEW", "xp_reward": 80},
            {"title": "Complete your Bag", "description": "Provide the final participation evidence requested by the project.", "category": "BAG_WORK", "verification_type": "PROJECT_REVIEW", "xp_reward": 100},
        ],
    },
    {
        "name": "Discover → Community → Complete",
        "description": "A discovery pathway for community growth using evidence-backed activities rather than one-click self-attestation.",
        "category": "DISCOVER",
        "difficulty": "EASY",
        "max_users": 2500,
        "challenges": [
            {"title": "Discover the project", "description": "Review the project overview and official resources, then provide the requested evidence.", "category": "LEARN", "verification_type": "PROJECT_REVIEW", "xp_reward": 50},
            {"title": "Explore the community", "description": "Visit the project community or social hub and provide the requested evidence.", "category": "COMMUNITY", "verification_type": "PROJECT_REVIEW", "xp_reward": 70},
            {"title": "Complete the pathway", "description": "Submit the final evidence requested by the project for this Bag.", "category": "BAG_WORK", "verification_type": "PROJECT_REVIEW", "xp_reward": 90},
        ],
    },
]


class SaveTemplateIn(BaseModel):
    campaign_id: int
    name: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=1000)


class InstantiateIn(BaseModel):
    project_id: int
    title: str = Field(min_length=3, max_length=160)
    reward_asset: str = Field(min_length=1, max_length=24)
    funding_type: str = "TOKEN"
    token_allocation: Decimal = Field(gt=0)
    gross_reward_per_user: Decimal = Field(gt=0)
    max_users: int | None = Field(default=None, gt=0, le=1_000_000)


def _upgrade_legacy_blueprint(raw: dict) -> dict:
    """Read an old template safely without bringing legacy Mission execution back.

    Existing stored templates can still be opened, but their old mission shape is
    converted into a project-reviewed Challenge before use. SELF_ATTEST is never
    restored as a reward mechanism.
    """
    if "category" in raw:
        return raw
    mission_type = str(raw.get("mission_type") or "LEARN").upper()
    category = mission_type if mission_type in {"COMMUNITY", "CONTENT", "ONCHAIN", "LEARN"} else "BAG_WORK"
    config = {}
    if raw.get("quiz_answer"):
        config = {
            "question": raw.get("quiz_question") or raw.get("title"),
            "options": raw.get("quiz_options") or [],
            "answer": raw.get("quiz_answer"),
        }
        verification = "QUIZ"
    else:
        verification = "PROJECT_REVIEW"
    return {
        "title": raw.get("title") or "Template activity",
        "description": raw.get("description") or "Complete this activity and provide evidence.",
        "category": category,
        "verification_type": verification,
        "target_url": raw.get("target_url"),
        "config": config,
        "xp_reward": int(raw.get("xp_reward") or 50),
    }


def _blueprint(row: CampaignTemplate) -> list[dict]:
    return [_upgrade_legacy_blueprint(item) for item in json.loads(row.mission_blueprint)]


def ensure_system_templates(db: Session):
    for spec in SYSTEM_TEMPLATES:
        row = db.query(CampaignTemplate).filter(
            CampaignTemplate.is_system.is_(True), CampaignTemplate.name == spec["name"]
        ).first()
        if not row:
            db.add(CampaignTemplate(
                owner_id=None,
                name=spec["name"],
                description=spec["description"],
                category=spec["category"],
                difficulty=spec["difficulty"],
                default_max_users=spec["max_users"],
                mission_blueprint=json.dumps(spec["challenges"], separators=(",", ":")),
                is_system=True,
            ))
    db.commit()


def serialize(row: CampaignTemplate):
    challenges = _blueprint(row)
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "category": row.category,
        "difficulty": row.difficulty,
        "user_share_pct": str(row.user_share_pct),
        "nubagz_share_pct": str(row.nubagz_share_pct),
        "referral_share_pct": str(row.referral_share_pct),
        "default_max_users": row.default_max_users,
        "challenges": challenges,
        # Keep the response key during the UI migration; it contains Challenge
        # blueprints, not executable legacy Missions.
        "missions": challenges,
        "onchain_rule_count": sum(1 for challenge in challenges if challenge.get("category") == "ONCHAIN"),
        "is_system": row.is_system,
        "created_at": row.created_at.isoformat(),
    }


def accessible_template(template_id: int, db: Session, user: User):
    ensure_system_templates(db)
    row = db.get(CampaignTemplate, template_id)
    if not row or not row.active or (not row.is_system and row.owner_id != user.id):
        raise HTTPException(404, "Campaign template not found")
    return row


@router.get("")
def list_templates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ensure_system_templates(db)
    rows = db.query(CampaignTemplate).filter(
        CampaignTemplate.active.is_(True),
        ((CampaignTemplate.is_system.is_(True)) | (CampaignTemplate.owner_id == user.id)),
    ).order_by(CampaignTemplate.is_system.desc(), CampaignTemplate.created_at.desc()).all()
    return [serialize(row) for row in rows]


@router.post("/from-campaign")
def save_from_campaign(data: SaveTemplateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, data.campaign_id)
    project = db.get(Project, campaign.project_id) if campaign else None
    if not campaign or not project or project.owner_id != user.id:
        raise HTTPException(404, "Campaign not found")
    challenges = db.query(Challenge).filter(Challenge.campaign_id == campaign.id).order_by(Challenge.position.asc()).all()
    if not challenges:
        raise HTTPException(400, "Campaign must contain at least one unified Challenge before it can become a template")
    blueprint = []
    for challenge in challenges:
        blueprint.append({
            "title": challenge.title,
            "description": challenge.description,
            "category": challenge.category,
            "provider": challenge.provider,
            "action": challenge.action,
            "verification_type": challenge.verification_type,
            "target_url": challenge.target_url,
            "target_id": challenge.target_id,
            "config": dict(challenge.config or {}),
            "xp_reward": challenge.xp_reward,
        })
    row = CampaignTemplate(
        owner_id=user.id,
        name=data.name,
        description=data.description,
        category=campaign.category,
        difficulty=campaign.difficulty,
        user_share_pct=campaign.user_share_pct,
        nubagz_share_pct=campaign.nubagz_share_pct,
        referral_share_pct=campaign.referral_share_pct,
        default_max_users=campaign.max_users,
        mission_blueprint=json.dumps(blueprint, separators=(",", ":")),
        is_system=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize(row)


@router.post("/{template_id}/instantiate")
def instantiate(template_id: int, data: InstantiateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    template = accessible_template(template_id, db, user)
    project = db.get(Project, data.project_id)
    if not project or project.owner_id != user.id:
        raise HTTPException(404, "Project not found")
    if project.status not in PUBLIC_PROJECT_STATUSES:
        raise HTTPException(400, "Suspended or archived projects cannot create a Bag")

    challenge_specs = [ChallengeCreate(**raw) for raw in _blueprint(template)]
    max_users = data.max_users or template.default_max_users
    required = data.gross_reward_per_user * Decimal(max_users)
    if data.token_allocation < required:
        raise HTTPException(400, f"Token allocation must cover the maximum gross reward obligation of {required} {data.reward_asset.upper()}")
    validated = CampaignCreate(
        project_id=project.id,
        title=data.title,
        description=template.description,
        category=template.category,
        difficulty=template.difficulty,
        reward_asset=data.reward_asset.upper(),
        funding_type=data.funding_type,
        token_allocation=data.token_allocation,
        gross_reward_per_user=data.gross_reward_per_user,
        user_share_pct=template.user_share_pct,
        nubagz_share_pct=template.nubagz_share_pct,
        referral_share_pct=template.referral_share_pct,
        max_users=max_users,
        missions=[],
        challenges=challenge_specs,
    )
    campaign = Campaign(**validated.model_dump(exclude={"missions", "challenges"}), status="DRAFT")
    db.add(campaign)
    db.flush()
    for idx, challenge_data in enumerate(validated.challenges):
        db.add(Challenge(
            campaign_id=campaign.id,
            position=idx,
            **challenge_data.model_dump(exclude={"gas_sponsorship"}),
        ))
    db.commit()
    db.refresh(campaign)
    return {
        "id": campaign.id,
        "title": campaign.title,
        "status": campaign.status,
        "project_id": campaign.project_id,
        "reward_asset": campaign.reward_asset,
        "max_users": campaign.max_users,
        "challenges_created": len(validated.challenges),
        "missions_created": 0,
        "onchain_rules_created": 0,
        "funding_status": "UNFUNDED",
        "message": "Template instantiated as a unified Challenge-based Bag draft. Verify reward funding before it becomes discoverable.",
    }
