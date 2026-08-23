from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import require_admin
from ..models import User, Project, Campaign, Enrollment, LedgerEntry, Withdrawal, FraudFlag
from ..economy_models import CampaignFunding
from ..integration_models import GasSponsorshipPolicy
from ..risk_models import FraudSignal
from ..schemas import AdminDecision

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    legacy_flags = db.query(func.count(FraudFlag.id)).filter(FraudFlag.status == "OPEN").scalar() or 0
    risk_signals = db.query(func.count(FraudSignal.id)).filter(FraudSignal.status == "OPEN").scalar() or 0
    return {
        "users": db.query(func.count(User.id)).scalar() or 0,
        "projects": db.query(func.count(Project.id)).scalar() or 0,
        "live_projects": db.query(func.count(Project.id)).filter(Project.status.in_(["LIVE","APPROVED"])).scalar() or 0,
        "suspended_projects": db.query(func.count(Project.id)).filter(Project.status == "SUSPENDED").scalar() or 0,
        "live_campaigns": db.query(func.count(Campaign.id)).filter(Campaign.status == "LIVE").scalar() or 0,
        "suspended_campaigns": db.query(func.count(Campaign.id)).filter(Campaign.status == "SUSPENDED").scalar() or 0,
        "completions": db.query(func.count(Enrollment.id)).filter(Enrollment.status == "COMPLETED").scalar() or 0,
        "pending_withdrawals": db.query(func.count(Withdrawal.id)).filter(Withdrawal.status == "PENDING").scalar() or 0,
        "active_gas_passes": db.query(func.count(GasSponsorshipPolicy.id)).filter(GasSponsorshipPolicy.status == "ACTIVE").scalar() or 0,
        "gas_funding_pending": db.query(func.count(GasSponsorshipPolicy.id)).filter(GasSponsorshipPolicy.funding_status != "VERIFIED").scalar() or 0,
        "open_flags": int(legacy_flags) + int(risk_signals),
    }


@router.get("/projects")
def projects(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(Project).order_by(Project.created_at.desc()).all()
    return [{"id":p.id,"name":p.name,"symbol":p.symbol,"chain":p.chain,"status":p.status,"owner_id":p.owner_id,"created_at":p.created_at.isoformat()} for p in rows]


@router.patch("/projects/{project_id}")
def moderate_project(project_id: int, data: AdminDecision, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    project = db.get(Project, project_id)
    if not project: raise HTTPException(404, "Project not found")
    status = data.status.upper()
    if status not in {"LIVE","SUSPENDED","ARCHIVED"}: raise HTTPException(400, "Project moderation status must be LIVE, SUSPENDED or ARCHIVED")
    project.status = status; db.commit(); return {"ok":True,"status":project.status}


@router.get("/campaigns")
def campaigns(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(Campaign).order_by(Campaign.created_at.desc()).all(); funding_rows = {f.campaign_id:f for f in db.query(CampaignFunding).all()}
    return [{"id":c.id,"title":c.title,"project_id":c.project_id,"asset":c.reward_asset,"allocation":str(c.token_allocation),"status":c.status,"featured":c.featured,"funding_status":funding_rows[c.id].status if c.id in funding_rows else "UNFUNDED","created_at":c.created_at.isoformat()} for c in rows]


@router.patch("/campaigns/{campaign_id}")
def moderate_campaign(campaign_id: int, data: AdminDecision, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign: raise HTTPException(404, "Campaign not found")
    status = data.status.upper()
    if status not in {"LIVE","PAUSED","SUSPENDED","COMPLETED","DRAFT"}: raise HTTPException(400, "Invalid Bag moderation status")
    if status == "LIVE":
        project = db.get(Project,campaign.project_id)
        if not project or project.status not in {"LIVE","APPROVED"}: raise HTTPException(409,"Restore the project before restoring this Bag")
        funding = db.query(CampaignFunding).filter(CampaignFunding.campaign_id == campaign_id).first(); required = Decimal(campaign.gross_reward_per_user) * Decimal(campaign.max_users)
        if not funding or funding.status != "VERIFIED" or Decimal(funding.verified_amount) < required: raise HTTPException(400, f"Bag cannot be live until {required} {campaign.reward_asset} of reward funding is verified")
    campaign.status = status; db.commit(); return {"ok":True,"status":campaign.status}


@router.get("/treasury")
def treasury(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(LedgerEntry.asset_symbol, func.sum(LedgerEntry.amount)).filter(LedgerEntry.user_id.is_(None)).group_by(LedgerEntry.asset_symbol).all()
    return [{"asset":asset,"amount":str(amount or 0)} for asset,amount in rows]


@router.get("/withdrawals")
def withdrawals(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(Withdrawal).order_by(Withdrawal.created_at.desc()).all()
    return [{"id":w.id,"user_id":w.user_id,"asset":w.asset_symbol,"amount":str(w.amount),"chain":w.chain,"wallet_address":w.wallet_address,"status":w.status,"tx_hash":w.tx_hash} for w in rows]
