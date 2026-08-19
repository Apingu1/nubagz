from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import User, Project, LedgerEntry
from ..economy_models import BagDrop, BagDropItem, BagDropClaim

router = APIRouter(prefix="/api/bagdrops", tags=["bagdrops"])


class DropItemIn(BaseModel):
    asset: str = Field(min_length=1, max_length=24)
    amount_per_claim: Decimal = Field(gt=0)
    funded_amount: Decimal = Field(gt=0)


class BagDropCreateIn(BaseModel):
    project_id: int
    title: str = Field(min_length=3, max_length=160)
    rarity: str = "COMMON"
    max_claims: int = Field(gt=0, le=100000)
    min_bag_score: int = Field(default=0, ge=0, le=1000)
    funding_tx_hash: str = Field(min_length=4, max_length=255)
    items: list[DropItemIn] = Field(min_length=1, max_length=10)


def serialize(drop: BagDrop, db: Session, user_id: int | None = None):
    items = db.query(BagDropItem).filter(BagDropItem.drop_id == drop.id).all()
    claimed = False
    if user_id:
        claimed = db.query(BagDropClaim).filter(BagDropClaim.drop_id == drop.id, BagDropClaim.user_id == user_id).first() is not None
    return {
        "id": drop.id,
        "project_id": drop.project_id,
        "title": drop.title,
        "rarity": drop.rarity,
        "status": drop.status,
        "max_claims": drop.max_claims,
        "claims_count": drop.claims_count,
        "remaining_claims": max(0, drop.max_claims - drop.claims_count),
        "min_bag_score": drop.min_bag_score,
        "funding_status": drop.funding_status,
        "funding_tx_hash": drop.funding_tx_hash,
        "claimed": claimed,
        "items": [{
            "asset": item.asset_symbol,
            "amount_per_claim": str(item.amount_per_claim),
            "funded_amount": str(item.funded_amount),
            "distributed_amount": str(item.distributed_amount),
        } for item in items],
        "created_at": drop.created_at.isoformat(),
    }


@router.get("")
def list_bagdrops(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(BagDrop).filter(BagDrop.status == "LIVE").order_by(BagDrop.rarity.desc(), BagDrop.created_at.desc()).all()
    return [serialize(row, db, user.id) for row in rows]


@router.get("/mine")
def my_bagdrops(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(BagDrop).filter(BagDrop.created_by_id == user.id).order_by(BagDrop.created_at.desc()).all()
    return [serialize(row, db, user.id) for row in rows]


@router.post("")
def create_bagdrop(data: BagDropCreateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = db.get(Project, data.project_id)
    if not project or project.owner_id != user.id:
        raise HTTPException(404, "Project not found")
    if project.status != "APPROVED":
        raise HTTPException(400, "Project must be approved before creating a BagDrop")
    rarity = data.rarity.upper()
    if rarity not in {"COMMON", "RARE", "EPIC", "LEGENDARY"}:
        raise HTTPException(400, "Invalid BagDrop rarity")
    for item in data.items:
        required = item.amount_per_claim * data.max_claims
        if item.funded_amount < required:
            raise HTTPException(400, f"{item.asset.upper()} funding must cover {required} for all possible claims")
    drop = BagDrop(project_id=project.id, created_by_id=user.id, title=data.title, rarity=rarity, max_claims=data.max_claims, min_bag_score=data.min_bag_score, funding_tx_hash=data.funding_tx_hash, status="PENDING", funding_status="DECLARED")
    db.add(drop)
    db.flush()
    for item in data.items:
        db.add(BagDropItem(drop_id=drop.id, asset_symbol=item.asset.upper(), amount_per_claim=item.amount_per_claim, funded_amount=item.funded_amount))
    db.commit()
    db.refresh(drop)
    return serialize(drop, db, user.id)


@router.post("/{drop_id}/activate")
def activate_bagdrop(drop_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    drop = db.get(BagDrop, drop_id)
    if not drop:
        raise HTTPException(404, "BagDrop not found")
    items = db.query(BagDropItem).filter(BagDropItem.drop_id == drop.id).all()
    if not drop.funding_tx_hash or not items:
        raise HTTPException(400, "BagDrop funding must be declared before activation")
    for item in items:
        required = Decimal(item.amount_per_claim) * Decimal(drop.max_claims)
        if Decimal(item.funded_amount) < required:
            raise HTTPException(400, f"BagDrop is underfunded for {item.asset_symbol}")
    drop.funding_status = "VERIFIED"
    drop.status = "LIVE"
    db.commit()
    return serialize(drop, db)


@router.post("/{drop_id}/claim")
def claim_bagdrop(drop_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    drop = db.query(BagDrop).filter(BagDrop.id == drop_id).with_for_update().first()
    if not drop or drop.status != "LIVE" or drop.funding_status != "VERIFIED":
        raise HTTPException(404, "BagDrop is not available")
    if user.bag_score < drop.min_bag_score:
        raise HTTPException(403, f"BagScore {drop.min_bag_score}+ required")
    if drop.claims_count >= drop.max_claims:
        raise HTTPException(409, "BagDrop is fully claimed")
    if db.query(BagDropClaim).filter(BagDropClaim.drop_id == drop.id, BagDropClaim.user_id == user.id).first():
        raise HTTPException(409, "You already claimed this BagDrop")
    items = db.query(BagDropItem).filter(BagDropItem.drop_id == drop.id).with_for_update().all()
    rewards = []
    for item in items:
        remaining = Decimal(item.funded_amount) - Decimal(item.distributed_amount)
        if remaining < Decimal(item.amount_per_claim):
            raise HTTPException(409, f"{item.asset_symbol} BagDrop inventory is exhausted")
        amount = Decimal(item.amount_per_claim)
        item.distributed_amount = Decimal(item.distributed_amount) + amount
        db.add(LedgerEntry(user_id=user.id, campaign_id=None, asset_symbol=item.asset_symbol, amount=amount, entry_type="BAGDROP_REWARD", note=f"Opened {drop.title}"))
        rewards.append({"asset": item.asset_symbol, "amount": str(amount)})
    db.add(BagDropClaim(drop_id=drop.id, user_id=user.id))
    drop.claims_count += 1
    db.commit()
    return {"ok": True, "drop_id": drop.id, "rewards": rewards}
