from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import require_admin
from ..models import User, Project, Campaign, Enrollment, LedgerEntry, Withdrawal, FraudFlag
from ..schemas import AdminDecision

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return {
        "users": db.query(func.count(User.id)).scalar() or 0,
        "projects": db.query(func.count(Project.id)).scalar() or 0,
        "live_campaigns": db.query(func.count(Campaign.id)).filter(Campaign.status == "LIVE").scalar() or 0,
        "completions": db.query(func.count(Enrollment.id)).filter(Enrollment.status == "COMPLETED").scalar() or 0,
        "pending_projects": db.query(func.count(Project.id)).filter(Project.status == "PENDING").scalar() or 0,
        "pending_campaigns": db.query(func.count(Campaign.id)).filter(Campaign.status == "PENDING").scalar() or 0,
        "pending_withdrawals": db.query(func.count(Withdrawal.id)).filter(Withdrawal.status == "PENDING").scalar() or 0,
        "open_flags": db.query(func.count(FraudFlag.id)).filter(FraudFlag.status == "OPEN").scalar() or 0,
    }


@router.get("/projects")
def projects(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(Project).order_by(Project.created_at.desc()).all()
    return [{"id": p.id, "name": p.name, "symbol": p.symbol, "chain": p.chain, "status": p.status, "owner_id": p.owner_id, "created_at": p.created_at.isoformat()} for p in rows]


@router.patch("/projects/{project_id}")
def decide_project(project_id: int, data: AdminDecision, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if data.status not in {"APPROVED", "REJECTED", "SUSPENDED", "PENDING"}:
        raise HTTPException(400, "Invalid status")
    project.status = data.status
    db.commit()
    return {"ok": True, "status": project.status}


@router.get("/campaigns")
def campaigns(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    return [{"id": c.id, "title": c.title, "project_id": c.project_id, "asset": c.reward_asset, "allocation": str(c.token_allocation), "status": c.status, "featured": c.featured, "created_at": c.created_at.isoformat()} for c in rows]


@router.patch("/campaigns/{campaign_id}")
def decide_campaign(campaign_id: int, data: AdminDecision, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    if data.status not in {"LIVE", "REJECTED", "SUSPENDED", "PENDING", "COMPLETED"}:
        raise HTTPException(400, "Invalid status")
    campaign.status = data.status
    db.commit()
    return {"ok": True, "status": campaign.status}


@router.get("/treasury")
def treasury(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(LedgerEntry.asset_symbol, func.sum(LedgerEntry.amount)).filter(LedgerEntry.user_id.is_(None)).group_by(LedgerEntry.asset_symbol).all()
    return [{"asset": asset, "amount": str(amount or 0)} for asset, amount in rows]


@router.get("/withdrawals")
def withdrawals(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(Withdrawal).order_by(Withdrawal.created_at.desc()).all()
    return [{"id": w.id, "user_id": w.user_id, "asset": w.asset_symbol, "amount": str(w.amount), "chain": w.chain, "wallet_address": w.wallet_address, "status": w.status, "tx_hash": w.tx_hash} for w in rows]
