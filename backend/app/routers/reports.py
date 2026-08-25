from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..engagement_models import DisputeMessage, ProjectReview, SafetyReport
from ..models import Campaign, Project, User

router = APIRouter(prefix="/api/reports", tags=["reports-disputes"])


class ReportIn(BaseModel):
    target_type: str
    target_id: int
    category: str = Field(min_length=3, max_length=48)
    detail: str = Field(min_length=20, max_length=5000)


class MessageIn(BaseModel):
    message: str = Field(min_length=3, max_length=5000)


class ResolutionIn(BaseModel):
    status: str
    action: str = "NONE"
    note: str = Field(min_length=5, max_length=5000)


def target_owner(target_type: str, target_id: int, db: Session):
    """Resolve current targets plus historical REVIEW cases already in the DB."""
    kind = target_type.upper()
    if kind == "PROJECT":
        project = db.get(Project, target_id)
        if not project:
            raise HTTPException(404, "Project not found")
        return project.owner_id, project
    if kind == "CAMPAIGN":
        campaign = db.get(Campaign, target_id)
        project = db.get(Project, campaign.project_id) if campaign else None
        if not campaign or not project:
            raise HTTPException(404, "Campaign not found")
        return project.owner_id, campaign
    if kind == "REVIEW":
        review = db.get(ProjectReview, target_id)
        if not review:
            raise HTTPException(404, "Historical review not found")
        return review.user_id, review
    raise HTTPException(400, "Report target must be PROJECT or CAMPAIGN")


def can_access(row: SafetyReport, user: User, db: Session):
    owner_id, _ = target_owner(row.target_type, row.target_id, db)
    return user.role == "ADMIN" or row.reporter_id == user.id or owner_id == user.id


def author_label(row: SafetyReport, message: DisputeMessage, viewer: User, db: Session):
    author = db.get(User, message.author_id)
    if not author:
        return "Unknown"
    if message.author_id == row.reporter_id and viewer.role != "ADMIN" and viewer.id != row.reporter_id:
        return "Participant"
    return author.username


def serialize(row: SafetyReport, db: Session, viewer: User):
    messages = db.query(DisputeMessage).filter(
        DisputeMessage.report_id == row.id
    ).order_by(DisputeMessage.created_at.asc()).all()
    owner_id, _ = target_owner(row.target_type, row.target_id, db)
    reporter = db.get(User, row.reporter_id)
    return {
        "id": row.id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "category": row.category,
        "detail": row.detail,
        "status": row.status,
        "resolution_action": row.resolution_action,
        "resolution_note": row.resolution_note,
        "created_at": row.created_at.isoformat(),
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "reporter": reporter.username if (viewer.role == "ADMIN" or viewer.id == row.reporter_id) and reporter else "Participant",
        "is_reporter": viewer.id == row.reporter_id,
        "is_target_owner": viewer.id == owner_id,
        "messages": [
            {
                "id": message.id,
                "author": author_label(row, message, viewer, db),
                "message": message.message,
                "created_at": message.created_at.isoformat(),
            }
            for message in messages
        ],
    }


@router.post("")
def create_report(
    data: ReportIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kind = data.target_type.upper()
    if kind not in {"PROJECT", "CAMPAIGN"}:
        raise HTTPException(400, "Report target must be PROJECT or CAMPAIGN")
    category = data.category.upper()
    target_owner(kind, data.target_id, db)
    duplicate = db.query(SafetyReport).filter(
        SafetyReport.reporter_id == user.id,
        SafetyReport.target_type == kind,
        SafetyReport.target_id == data.target_id,
        SafetyReport.category == category,
        SafetyReport.status == "OPEN",
    ).first()
    if duplicate:
        raise HTTPException(409, f"You already have open case #{duplicate.id} for this target and category")
    row = SafetyReport(
        reporter_id=user.id,
        target_type=kind,
        target_id=data.target_id,
        category=category,
        detail=data.detail,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize(row, db, user)


@router.get("/mine")
def my_reports(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(SafetyReport).filter(
        SafetyReport.reporter_id == user.id
    ).order_by(SafetyReport.created_at.desc()).all()
    return [serialize(row, db, user) for row in rows]


@router.get("/affected")
def affected_reports(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(SafetyReport).order_by(SafetyReport.created_at.desc()).all()
    out = []
    for row in rows:
        try:
            owner_id, _ = target_owner(row.target_type, row.target_id, db)
            if owner_id == user.id:
                out.append(serialize(row, db, user))
        except HTTPException:
            pass
    return out


@router.get("/admin")
def admin_reports(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rows = db.query(SafetyReport).order_by(
        SafetyReport.status.asc(), SafetyReport.created_at.desc()
    ).all()
    return [serialize(row, db, user) for row in rows]


@router.get("/{report_id}")
def report_thread(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(SafetyReport, report_id)
    if not row or not can_access(row, user, db):
        raise HTTPException(404, "Report not found")
    return serialize(row, db, user)


@router.post("/{report_id}/messages")
def add_message(
    report_id: int,
    data: MessageIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(SafetyReport, report_id)
    if not row or not can_access(row, user, db):
        raise HTTPException(404, "Report not found")
    if row.status in {"RESOLVED", "DISMISSED"}:
        raise HTTPException(409, "This case is closed")
    db.add(DisputeMessage(report_id=row.id, author_id=user.id, message=data.message))
    db.commit()
    return serialize(row, db, user)


@router.post("/{report_id}/resolve")
def resolve_report(
    report_id: int,
    data: ResolutionIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = db.get(SafetyReport, report_id)
    if not row:
        raise HTTPException(404, "Report not found")
    if row.status in {"RESOLVED", "DISMISSED"}:
        raise HTTPException(409, "This case already has a final moderation decision")
    status = data.status.upper()
    action = data.action.upper()
    if status not in {"RESOLVED", "DISMISSED"}:
        raise HTTPException(400, "Resolution status must be RESOLVED or DISMISSED")
    if action not in {"NONE", "SUSPEND_PROJECT", "SUSPEND_CAMPAIGN"}:
        raise HTTPException(400, "Invalid resolution action")
    if status == "DISMISSED" and action != "NONE":
        raise HTTPException(400, "Dismissed cases cannot apply a moderation penalty")
    if action == "SUSPEND_PROJECT":
        if row.target_type != "PROJECT":
            raise HTTPException(400, "SUSPEND_PROJECT requires a project report")
        target = db.get(Project, row.target_id)
        target.status = "SUSPENDED"
    elif action == "SUSPEND_CAMPAIGN":
        if row.target_type != "CAMPAIGN":
            raise HTTPException(400, "SUSPEND_CAMPAIGN requires a campaign report")
        target = db.get(Campaign, row.target_id)
        target.status = "SUSPENDED"

    row.status = status
    row.resolution_action = action
    row.resolution_note = data.note
    row.reviewed_by_id = admin.id
    row.resolved_at = datetime.now(UTC)
    db.commit()
    return serialize(row, db, admin)
