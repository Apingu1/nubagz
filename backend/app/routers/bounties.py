from datetime import datetime, UTC
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import User, Project, LedgerEntry
from ..marketplace_models import Bounty, BountySubmission
from .risk import evaluate_user

router = APIRouter(prefix="/api/bounties", tags=["bounties"])


class BountyIn(BaseModel):
    project_id: int
    title: str = Field(min_length=4, max_length=180)
    description: str = Field(min_length=20, max_length=5000)
    reward_asset: str = Field(min_length=1, max_length=24)
    reward_per_winner: Decimal = Field(gt=0)
    max_winners: int = Field(gt=0, le=10000)
    funded_amount: Decimal = Field(gt=0)
    funding_reference: str = Field(min_length=4, max_length=255)


class FundingVerifyIn(BaseModel):
    funded_amount: Decimal = Field(gt=0)
    funding_reference: str = Field(min_length=4, max_length=255)


class SubmissionIn(BaseModel):
    evidence: str = Field(min_length=4, max_length=10000)


class DecisionIn(BaseModel):
    status: str


def required_obligation(row: Bounty) -> Decimal:
    return Decimal(row.reward_per_winner) * Decimal(row.max_winners)


def serialize_bounty(row: Bounty, db: Session, user_id: int | None = None, include_funding_details: bool = False):
    project = db.get(Project, row.project_id)
    mine = None
    if user_id:
        mine = db.query(BountySubmission).filter(
            BountySubmission.bounty_id == row.id,
            BountySubmission.user_id == user_id,
        ).first()
    payload = {
        "id": row.id,
        "project_id": row.project_id,
        "project_name": project.name if project else None,
        "title": row.title,
        "description": row.description,
        "reward_asset": row.reward_asset,
        "reward_per_winner": str(row.reward_per_winner),
        "max_winners": row.max_winners,
        "winners_count": row.winners_count,
        "remaining_winners": max(0, row.max_winners-row.winners_count),
        "funded_amount": str(row.funded_amount),
        "distributed_amount": str(row.distributed_amount),
        "remaining_funded_amount": str(max(Decimal("0"), Decimal(row.funded_amount)-Decimal(row.distributed_amount))),
        "maximum_obligation": str(required_obligation(row)),
        "funding_status": row.funding_status,
        "status": row.status,
        "my_submission_status": mine.status if mine else None,
        "created_at": row.created_at.isoformat(),
    }
    if include_funding_details:
        payload["funding_reference"] = row.funding_reference
    return payload


def serialize_submission(row: BountySubmission, db: Session):
    user = db.get(User, row.user_id)
    bounty = db.get(Bounty, row.bounty_id)
    return {
        "id": row.id,
        "bounty_id": row.bounty_id,
        "bounty_title": bounty.title if bounty else None,
        "user_id": row.user_id,
        "username": user.username if user else None,
        "evidence": row.evidence,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
    }


@router.get("")
def live_bounties(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Bounty).filter(
        Bounty.status == "LIVE",
        Bounty.funding_status == "VERIFIED",
    ).order_by(Bounty.created_at.desc()).all()
    return [serialize_bounty(row, db, user.id) for row in rows]


@router.get("/mine")
def my_bounties(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Bounty).filter(
        Bounty.created_by_id == user.id
    ).order_by(Bounty.created_at.desc()).all()
    return [serialize_bounty(row, db, user.id, include_funding_details=True) for row in rows]


@router.get("/admin")
def admin_bounties(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rows = db.query(Bounty).order_by(Bounty.created_at.desc()).all()
    return [serialize_bounty(row, db, user.id, include_funding_details=True) for row in rows]


@router.get("/review")
def review_queue(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(BountySubmission).join(
        Bounty, Bounty.id == BountySubmission.bounty_id
    ).join(
        Project, Project.id == Bounty.project_id
    ).filter(
        Project.owner_id == user.id
    ).order_by(BountySubmission.created_at.desc()).all()
    return [serialize_submission(row, db) for row in rows]


@router.get("/submissions/mine")
def my_submissions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(BountySubmission).filter(
        BountySubmission.user_id == user.id
    ).order_by(BountySubmission.created_at.desc()).all()
    return [serialize_submission(row, db) for row in rows]


@router.post("")
def create_bounty(data: BountyIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = db.get(Project, data.project_id)
    if not project or project.owner_id != user.id:
        raise HTTPException(404, "Project not found")
    if project.status != "APPROVED":
        raise HTTPException(400, "Project must be approved before creating a bounty")
    required = data.reward_per_winner * data.max_winners
    if data.funded_amount < required:
        raise HTTPException(400, f"Bounty funding must cover the full {required} {data.reward_asset.upper()} maximum obligation")
    row = Bounty(
        project_id=project.id,
        created_by_id=user.id,
        title=data.title,
        description=data.description,
        reward_asset=data.reward_asset.upper(),
        reward_per_winner=data.reward_per_winner,
        max_winners=data.max_winners,
        funded_amount=data.funded_amount,
        funding_reference=data.funding_reference.strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_bounty(row, db, user.id, include_funding_details=True)


@router.post("/{bounty_id}/activate")
def activate_bounty(bounty_id: int, data: FundingVerifyIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    row = db.query(Bounty).filter(Bounty.id == bounty_id).with_for_update().first()
    if not row:
        raise HTTPException(404, "Bounty not found")
    if row.status != "PENDING" or row.funding_status == "VERIFIED":
        raise HTTPException(409, "Bounty funding has already been reviewed")
    required = required_obligation(row)
    if data.funded_amount < required:
        raise HTTPException(400, f"Verified funding must cover the full {required} {row.reward_asset} maximum obligation")
    row.funded_amount = data.funded_amount
    row.funding_reference = data.funding_reference.strip()
    row.funding_status = "VERIFIED"
    row.status = "LIVE"
    db.commit()
    return serialize_bounty(row, db, include_funding_details=True)


@router.post("/{bounty_id}/submit")
def submit_bounty(bounty_id: int, data: SubmissionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trust = evaluate_user(db, user)
    if trust.trust_level == "RESTRICTED":
        raise HTTPException(403, "This account is restricted from reward submissions pending trust review")
    row = db.get(Bounty, bounty_id)
    if not row or row.status != "LIVE" or row.funding_status != "VERIFIED":
        raise HTTPException(404, "Bounty is not available")
    project = db.get(Project, row.project_id)
    if project and project.owner_id == user.id:
        raise HTTPException(400, "Project owners cannot submit to their own funded bounty")
    if row.winners_count >= row.max_winners:
        raise HTTPException(409, "Bounty winner allocation is full")
    if db.query(BountySubmission).filter(
        BountySubmission.bounty_id == row.id,
        BountySubmission.user_id == user.id,
    ).first():
        raise HTTPException(409, "You already submitted to this bounty")
    submission = BountySubmission(bounty_id=row.id, user_id=user.id, evidence=data.evidence.strip())
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return serialize_submission(submission, db)


@router.post("/submissions/{submission_id}/decision")
def decide_submission(submission_id: int, data: DecisionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    status = data.status.upper()
    if status not in {"APPROVED", "REJECTED"}:
        raise HTTPException(400, "Invalid submission decision")

    pre_submission = db.get(BountySubmission, submission_id)
    if not pre_submission:
        raise HTTPException(404, "Bounty submission not found")
    participant = db.get(User, pre_submission.user_id)
    participant_trust = None
    if status == "APPROVED" and participant:
        participant_trust = evaluate_user(db, participant)

    submission = db.query(BountySubmission).filter(
        BountySubmission.id == submission_id
    ).with_for_update().first()
    bounty = db.query(Bounty).filter(
        Bounty.id == submission.bounty_id
    ).with_for_update().first() if submission else None
    project = db.get(Project, bounty.project_id) if bounty else None
    if not submission or not bounty or not project or project.owner_id != user.id:
        raise HTTPException(403, "Only the project owner can review this submission")
    if submission.status != "PENDING":
        raise HTTPException(409, "This submission has already been reviewed")

    if status == "APPROVED":
        if not participant or not participant_trust or participant_trust.trust_level == "RESTRICTED":
            raise HTTPException(409, "Submission cannot be rewarded while the user is Restricted")
        if bounty.status != "LIVE" or bounty.funding_status != "VERIFIED":
            raise HTTPException(409, "Bounty is not available for payout")
        if bounty.winners_count >= bounty.max_winners:
            raise HTTPException(409, "Bounty winner allocation is full")
        remaining = Decimal(bounty.funded_amount) - Decimal(bounty.distributed_amount)
        reward = Decimal(bounty.reward_per_winner)
        if remaining < reward:
            raise HTTPException(409, "Verified bounty inventory is exhausted")
        bounty.winners_count += 1
        bounty.distributed_amount = Decimal(bounty.distributed_amount) + reward
        db.add(LedgerEntry(
            user_id=submission.user_id,
            campaign_id=None,
            asset_symbol=bounty.reward_asset,
            amount=reward,
            entry_type="BOUNTY_REWARD",
            note=f"Approved bounty: {bounty.title}",
        ))
        if bounty.winners_count >= bounty.max_winners:
            bounty.status = "COMPLETED"
    submission.status = status
    submission.reviewed_by_id = user.id
    submission.reviewed_at = datetime.now(UTC)
    db.commit()
    return serialize_submission(submission, db)
