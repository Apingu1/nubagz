from datetime import datetime, UTC
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Project, Campaign, LedgerEntry
from ..marketplace_models import BagBuilderPathway, BountySubmission
from ..engagement_models import Notification

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def add_once(db: Session, user_id: int, key: str, ntype: str, title: str, message: str, link_path: str | None = None) -> bool:
    if db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.dedupe_key == key,
    ).first():
        return False
    try:
        with db.begin_nested():
            db.add(Notification(
                user_id=user_id,
                dedupe_key=key,
                notification_type=ntype,
                title=title,
                message=message,
                link_path=link_path,
            ))
            db.flush()
        return True
    except IntegrityError:
        # A concurrent inbox sync may have inserted the same user/key first.
        # The database uniqueness constraint remains authoritative.
        return False


def sync_user_notifications(db: Session, user: User):
    entries = db.query(LedgerEntry).filter(
        LedgerEntry.user_id == user.id
    ).order_by(LedgerEntry.id.desc()).limit(100).all()
    for entry in entries:
        label = entry.entry_type.replace("_", " ").title()
        add_once(
            db,
            user.id,
            f"ledger:{entry.id}",
            "REWARD",
            f"{label} received",
            f"{entry.amount} {entry.asset_symbol} was added to your NuBagz balance.",
            "/app/earnings",
        )

    projects = db.query(Project).filter(Project.owner_id == user.id).all()
    for project in projects:
        if project.status in {"APPROVED", "REJECTED", "SUSPENDED"}:
            add_once(
                db,
                user.id,
                f"project:{project.id}:{project.status}",
                "PROJECT",
                f"{project.name}: {project.status.title()}",
                f"Your project {project.name} is now {project.status.lower()}.",
                "/app/studio",
            )

    project_ids = [p.id for p in projects]
    if project_ids:
        campaigns = db.query(Campaign).filter(Campaign.project_id.in_(project_ids)).all()
        for campaign in campaigns:
            if campaign.status in {"LIVE", "REJECTED", "SUSPENDED", "COMPLETED"}:
                add_once(
                    db,
                    user.id,
                    f"campaign:{campaign.id}:{campaign.status}",
                    "CAMPAIGN",
                    f"{campaign.title}: {campaign.status.title()}",
                    f"Your Bag campaign is now {campaign.status.lower()}.",
                    "/app/studio",
                )

    pathways = db.query(BagBuilderPathway).filter(
        BagBuilderPathway.creator_id == user.id,
        BagBuilderPathway.status.in_(["APPROVED", "REJECTED"]),
    ).all()
    for pathway in pathways:
        add_once(
            db,
            user.id,
            f"builder:{pathway.id}:{pathway.status}",
            "BAGBUILDER",
            f"BagBuilder pathway {pathway.status.title()}",
            pathway.title,
            "/app/builders",
        )

    submissions = db.query(BountySubmission).filter(
        BountySubmission.user_id == user.id,
        BountySubmission.status.in_(["APPROVED", "REJECTED"]),
    ).all()
    for submission in submissions:
        add_once(
            db,
            user.id,
            f"bounty-submission:{submission.id}:{submission.status}",
            "BOUNTY",
            f"Bounty submission {submission.status.title()}",
            "Your bounty submission has been reviewed by the project owner.",
            "/app/bounties",
        )
    db.commit()


def serialize(row: Notification):
    return {
        "id": row.id,
        "type": row.notification_type,
        "title": row.title,
        "message": row.message,
        "link_path": row.link_path,
        "read": row.read_at is not None,
        "created_at": row.created_at.isoformat(),
        "read_at": row.read_at.isoformat() if row.read_at else None,
    }


@router.get("")
def notifications(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sync_user_notifications(db, user)
    rows = db.query(Notification).filter(
        Notification.user_id == user.id
    ).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(100).all()
    unread = sum(1 for row in rows if row.read_at is None)
    return {
        "unread_count": unread,
        "total_count": len(rows),
        "notifications": [serialize(row) for row in rows],
    }


@router.post("/read-all")
def read_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sync_user_notifications(db, user)
    rows = db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.read_at.is_(None),
    ).all()
    now = datetime.now(UTC)
    for row in rows:
        row.read_at = now
    db.commit()
    return {"ok": True, "marked_read": len(rows)}


@router.post("/{notification_id}/read")
def read_notification(notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user.id,
    ).first()
    if not row:
        raise HTTPException(404, "Notification not found")
    if not row.read_at:
        row.read_at = datetime.now(UTC)
        db.commit()
    return serialize(row)
