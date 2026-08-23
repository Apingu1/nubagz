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
from ..economy_models import OnchainRule

router = APIRouter(prefix="/api/templates", tags=["campaign-templates"])
PUBLIC_PROJECT_STATUSES={"LIVE","APPROVED"}

SYSTEM_TEMPLATES=[
 {"name":"Learn → Quiz → Claim","description":"A beginner onboarding flow that teaches the project, checks understanding and finishes with a funded completion.","category":"LEARN","difficulty":"EASY","max_users":1000,"missions":[{"title":"Meet the project","description":"Read the project briefing and understand the core utility.","mission_type":"LEARN","verification_type":"SELF_ATTEST","xp_reward":60},{"title":"Pass the knowledge check","description":"Answer a project-specific question configured after creation.","mission_type":"QUIZ","verification_type":"SELF_ATTEST","xp_reward":80},{"title":"Complete your Bag","description":"Finish the onboarding pathway and record the participation.","mission_type":"DISCOVER","verification_type":"SELF_ATTEST","xp_reward":100}]},
 {"name":"Discover → Community → Complete","description":"A lightweight discovery pathway for community growth without forcing an investment or deposit.","category":"DISCOVER","difficulty":"EASY","max_users":2500,"missions":[{"title":"Discover the project","description":"Review the project overview and official resources.","mission_type":"DISCOVER","verification_type":"SELF_ATTEST","xp_reward":50},{"title":"Explore the community","description":"Visit the project community or social hub.","mission_type":"COMMUNITY","verification_type":"SELF_ATTEST","xp_reward":70},{"title":"Complete the pathway","description":"Confirm you finished the discovery route.","mission_type":"DISCOVER","verification_type":"SELF_ATTEST","xp_reward":90}]},
]

class SaveTemplateIn(BaseModel):
    campaign_id:int;name:str=Field(min_length=3,max_length=160);description:str=Field(min_length=10,max_length=1000)
class InstantiateIn(BaseModel):
    project_id:int;title:str=Field(min_length=3,max_length=160);reward_asset:str=Field(min_length=1,max_length=24);funding_type:str="TOKEN";token_allocation:Decimal=Field(gt=0);gross_reward_per_user:Decimal=Field(gt=0);max_users:int|None=Field(default=None,gt=0,le=1_000_000)

def ensure_system_templates(db:Session):
    for spec in SYSTEM_TEMPLATES:
        if not db.query(CampaignTemplate).filter(CampaignTemplate.is_system.is_(True),CampaignTemplate.name==spec["name"]).first():db.add(CampaignTemplate(owner_id=None,name=spec["name"],description=spec["description"],category=spec["category"],difficulty=spec["difficulty"],default_max_users=spec["max_users"],mission_blueprint=json.dumps(spec["missions"],separators=(",",":")),is_system=True))
    db.commit()
def serialize(row:CampaignTemplate):
    missions=json.loads(row.mission_blueprint);return {"id":row.id,"name":row.name,"description":row.description,"category":row.category,"difficulty":row.difficulty,"user_share_pct":str(row.user_share_pct),"nubagz_share_pct":str(row.nubagz_share_pct),"referral_share_pct":str(row.referral_share_pct),"default_max_users":row.default_max_users,"missions":missions,"onchain_rule_count":sum(1 for mission in missions if mission.get("onchain_rule")),"is_system":row.is_system,"created_at":row.created_at.isoformat()}
def accessible_template(template_id:int,db:Session,user:User):
    ensure_system_templates(db);row=db.get(CampaignTemplate,template_id)
    if not row or not row.active or (not row.is_system and row.owner_id!=user.id):raise HTTPException(404,"Campaign template not found")
    return row

@router.get("")
def list_templates(db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    ensure_system_templates(db);rows=db.query(CampaignTemplate).filter(CampaignTemplate.active.is_(True),((CampaignTemplate.is_system.is_(True))|(CampaignTemplate.owner_id==user.id))).order_by(CampaignTemplate.is_system.desc(),CampaignTemplate.created_at.desc()).all();return [serialize(row) for row in rows]

@router.post("/from-campaign")
def save_from_campaign(data:SaveTemplateIn,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    campaign=db.get(Campaign,data.campaign_id);project=db.get(Project,campaign.project_id) if campaign else None
    if not campaign or not project or project.owner_id!=user.id:raise HTTPException(404,"Campaign not found")
    missions=db.query(Mission).filter(Mission.campaign_id==campaign.id).order_by(Mission.position.asc()).all()
    if not missions:raise HTTPException(400,"Campaign must contain at least one mission before it can become a template")
    blueprint=[]
    for mission in missions:
        item={"title":mission.title,"description":mission.description,"mission_type":mission.mission_type,"verification_type":mission.verification_type,"target_url":mission.target_url,"quiz_question":mission.quiz_question,"quiz_options":mission.quiz_options,"quiz_answer":mission.quiz_answer,"xp_reward":mission.xp_reward};rule=db.query(OnchainRule).filter(OnchainRule.mission_id==mission.id).first()
        if rule:item["onchain_rule"]={"chain":rule.chain,"rule_type":rule.rule_type,"contract_address":rule.contract_address,"min_amount":str(rule.min_amount) if rule.min_amount is not None else None,"token_decimals":rule.token_decimals}
        blueprint.append(item)
    row=CampaignTemplate(owner_id=user.id,name=data.name,description=data.description,category=campaign.category,difficulty=campaign.difficulty,user_share_pct=campaign.user_share_pct,nubagz_share_pct=campaign.nubagz_share_pct,referral_share_pct=campaign.referral_share_pct,default_max_users=campaign.max_users,mission_blueprint=json.dumps(blueprint,separators=(",",":")),is_system=False);db.add(row);db.commit();db.refresh(row);return serialize(row)

@router.post("/{template_id}/instantiate")
def instantiate(template_id:int,data:InstantiateIn,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    template=accessible_template(template_id,db,user);project=db.get(Project,data.project_id)
    if not project or project.owner_id!=user.id:raise HTTPException(404,"Project not found")
    if project.status not in PUBLIC_PROJECT_STATUSES:raise HTTPException(400,"Suspended or archived projects cannot create a Bag")
    raw_missions=json.loads(template.mission_blueprint);mission_specs=[]
    for raw in raw_missions:
        item=dict(raw);rule_spec=item.pop("onchain_rule",None);mission_specs.append((MissionCreate(**item),rule_spec))
    max_users=data.max_users or template.default_max_users;required=data.gross_reward_per_user*Decimal(max_users)
    if data.token_allocation<required:raise HTTPException(400,f"Token allocation must cover the maximum gross reward obligation of {required} {data.reward_asset.upper()}")
    validated=CampaignCreate(project_id=project.id,title=data.title,description=template.description,category=template.category,difficulty=template.difficulty,reward_asset=data.reward_asset.upper(),funding_type=data.funding_type,token_allocation=data.token_allocation,gross_reward_per_user=data.gross_reward_per_user,user_share_pct=template.user_share_pct,nubagz_share_pct=template.nubagz_share_pct,referral_share_pct=template.referral_share_pct,max_users=max_users,missions=[spec[0] for spec in mission_specs])
    campaign=Campaign(**validated.model_dump(exclude={"missions","challenges"}),status="DRAFT");db.add(campaign);db.flush();rules_created=0
    for idx,(mission_data,rule_spec) in enumerate(mission_specs):
        mission=Mission(campaign_id=campaign.id,position=idx,**mission_data.model_dump());db.add(mission);db.flush()
        if rule_spec:db.add(OnchainRule(mission_id=mission.id,chain=rule_spec.get("chain") or "Avalanche",rule_type=rule_spec.get("rule_type") or "TX_SUCCESS",contract_address=rule_spec.get("contract_address"),min_amount=Decimal(rule_spec["min_amount"]) if rule_spec.get("min_amount") is not None else None,token_decimals=int(rule_spec.get("token_decimals",18)),created_by_id=user.id));rules_created+=1
    db.commit();db.refresh(campaign)
    return {"id":campaign.id,"title":campaign.title,"status":campaign.status,"project_id":campaign.project_id,"reward_asset":campaign.reward_asset,"max_users":campaign.max_users,"missions_created":len(validated.missions),"onchain_rules_created":rules_created,"funding_status":"UNFUNDED","message":"Template instantiated as a creator-controlled Bag draft. Verify reward funding, then publish it yourself from Creator Studio; no content approval queue is required."}
