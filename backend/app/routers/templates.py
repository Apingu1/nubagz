import json
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Project, Campaign, Mission
from ..schemas import CampaignCreate, MissionCreate
from ..engagement_models import CampaignTemplate

router = APIRouter(prefix="/api/templates", tags=["campaign-templates"])


SYSTEM_TEMPLATES = [
    {
        "name": "Learn → Quiz → Claim",
        "description": "A beginner onboarding flow that teaches the project, checks understanding and finishes with a funded completion.",
        "category": "LEARN", "difficulty": "EASY", "max_users": 1000,
        "missions": [
            {"title":"Meet the project","description":"Read the project briefing and understand the core utility.","mission_type":"LEARN","verification_type":"SELF_ATTEST","xp_reward":60},
            {"title":"Pass the knowledge check","description":"Answer a project-specific question configured after creation.","mission_type":"QUIZ","verification_type":"SELF_ATTEST","xp_reward":80},
            {"title":"Complete your Bag","description":"Finish the onboarding pathway and record the participation.","mission_type":"DISCOVER","verification_type":"SELF_ATTEST","xp_reward":100},
        ],
    },
    {
        "name": "Discover → Community → Complete",
        "description": "A lightweight discovery pathway for community growth without forcing an investment or deposit.",
        "category": "DISCOVER", "difficulty": "EASY", "max_users": 2500,
        "missions": [
            {"title":"Discover the project","description":"Review the project overview and official resources.","mission_type":"DISCOVER","verification_type":"SELF_ATTEST","xp_reward":50},
            {"title":"Explore the community","description":"Visit the project community or social hub.","mission_type":"COMMUNITY","verification_type":"SELF_ATTEST","xp_reward":70},
            {"title":"Complete the pathway","description":"Confirm you finished the discovery route.","mission_type":"DISCOVER","verification_type":"SELF_ATTEST","xp_reward":90},
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


def ensure_system_templates(db: Session):
    for spec in SYSTEM_TEMPLATES:
        existing = db.query(CampaignTemplate).filter(CampaignTemplate.is_system.is_(True), CampaignTemplate.name == spec["name"]).first()
        if not existing:
            db.add(CampaignTemplate(owner_id=None, name=spec["name"], description=spec["description"], category=spec["category"], difficulty=spec["difficulty"], default_max_users=spec["max_users"], mission_blueprint=json.dumps(spec["missions"], separators=(",", ":")), is_system=True))
    db.commit()


def serialize(row: CampaignTemplate):
    return {
        "id": row.id, "name": row.name, "description": row.description, "category": row.category,
        "difficulty": row.difficulty, "user_share_pct": str(row.user_share_pct), "nubagz_share_pct": str(row.nubagz_share_pct),
        "referral_share_pct": str(row.referral_share_pct), "default_max_users": row.default_max_users,
        "missions": json.loads(row.mission_blueprint), "is_system": row.is_system, "created_at": row.created_at.isoformat(),
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
    rows = db.query(CampaignTemplate).filter(CampaignTemplate.active.is_(True), ((CampaignTemplate.is_system.is_(True)) | (CampaignTemplate.owner_id == user.id))).order_by(CampaignTemplate.is_system.desc(), CampaignTemplate.created_at.desc()).all()
    return [serialize(row) for row in rows]


@router.post("/from-campaign")
def save_from_campaign(data: SaveTemplateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = db.get(Campaign, data.campaign_id)
    project = db.get(Project, campaign.project_id) if campaign else None
    if not campaign or not project or project.owner_id != user.id:
        raise HTTPException(404, "Campaign not found")
    missions = db.query(Mission).filter(Mission.campaign_id == campaign.id).order_by(Mission.position.asc()).all()
    blueprint = [{
        "title": m.title, "description": m.description, "mission_type": m.mission_type, "verification_type": m.verification_type,
        "target_url": m.target_url, "quiz_question": m.quiz_question, "quiz_options": m.quiz_options, "quiz_answer": m.quiz_answer, "xp_reward": m.xp_reward,
    } for m in missions]
    row = CampaignTemplate(owner_id=user.id, name=data.name, description=data.description, category=campaign.category, difficulty=campaign.difficulty, user_share_pct=campaign.user_share_pct, nubagz_share_pct=campaign.nubagz_share_pct, referral_share_pct=campaign.referral_share_pct, default_max_users=campaign.max_users, mission_blueprint=json.dumps(blueprint, separators=(",", ":")), is_system=False)
    db.add(row); db.commit(); db.refresh(row)
    return serialize(row)


@router.post("/{template_id}/instantiate")
def instantiate(template_id: int, data: InstantiateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    template = accessible_template(template_id, db, user)
    project = db.get(Project, data.project_id)
    if not project or project.owner_id != user.id:
        raise HTTPException(404, "Project not found")
    if project.status != "APPROVED":
        raise HTTPException(400, "Project must be approved before a campaign can be created")
    raw_missions = json.loads(template.mission_blueprint)
    mission_inputs = [MissionCreate(**mission) for mission in raw_missions]
    max_users = data.max_users or template.default_max_users
    validated = CampaignCreate(project_id=project.id, title=data.title, description=template.description, category=template.category, difficulty=template.difficulty, reward_asset=data.reward_asset.upper(), funding_type=data.funding_type, token_allocation=data.token_allocation, gross_reward_per_user=data.gross_reward_per_user, user_share_pct=template.user_share_pct, nubagz_share_pct=template.nubagz_share_pct, referral_share_pct=template.referral_share_pct, max_users=max_users, missions=mission_inputs)
    campaign = Campaign(**validated.model_dump(exclude={"missions"}), status="PENDING")
    db.add(campaign); db.flush()
    for idx, mission_data in enumerate(validated.missions):
        db.add(Mission(campaign_id=campaign.id, position=idx, **mission_data.model_dump()))
    db.commit(); db.refresh(campaign)
    return {"id":campaign.id,"title":campaign.title,"status":campaign.status,"project_id":campaign.project_id,"reward_asset":campaign.reward_asset,"max_users":campaign.max_users,"missions_created":len(validated.missions),"funding_status":"UNFUNDED","message":"Template instantiated as a normal pending campaign. Funding verification and admin activation are still required."}
