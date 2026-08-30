from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..challenge_dependencies import dependency_preflight, require_server_dependencies
from ..challenge_models import Challenge
from ..db import get_db
from ..deps import get_current_user
from ..models import Campaign, Project, User
from ..schemas import ChallengeCompleteIn
from . import challenges as challenge_routes
from . import domain_v2 as domain_routes


router = APIRouter(tags=["challenge-dependencies"])


def _attach_preflight(db: Session, user: User, row: dict) -> dict:
    challenge = db.get(Challenge, int(row["id"]))
    if challenge:
        row = dict(row)
        row["dependency_preflight"] = dependency_preflight(db, user, challenge)
    return row


def _submission_project_id(db: Session, challenge_id: int) -> int | None:
    challenge = db.get(Challenge, challenge_id)
    campaign = db.get(Campaign, challenge.campaign_id) if challenge else None
    project = db.get(Project, campaign.project_id) if campaign else None
    return project.id if project else None


@router.get("/api/challenges")
def dependency_aware_bag_work(
    category: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = challenge_routes.list_bag_work(category=category, provider=provider, db=db, user=user)
    return [_attach_preflight(db, user, row) for row in rows]


@router.get("/api/challenges/campaigns/{campaign_id}")
def dependency_aware_campaign_bag_work(
    campaign_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    payload = challenge_routes.campaign_bag_work(campaign_id=campaign_id, db=db, user=user)
    payload = dict(payload)
    payload["challenges"] = [_attach_preflight(db, user, row) for row in payload.get("challenges", [])]
    return payload


@router.get("/api/challenges/submissions/project")
def dependency_aware_project_submissions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = challenge_routes.project_submissions(db=db, user=user)
    return [
        {**row, "project_id": _submission_project_id(db, int(row["challenge_id"]))}
        for row in rows
    ]


@router.get("/api/challenges/{challenge_id}")
def dependency_aware_challenge(
    challenge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    payload = domain_routes.canonical_challenge(challenge_id=challenge_id, db=db, user=user)
    return _attach_preflight(db, user, payload)


@router.post("/api/challenges/{challenge_id}/join")
def dependency_aware_join(
    challenge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge = db.get(Challenge, challenge_id)
    if challenge:
        require_server_dependencies(db, user, challenge)
    return domain_routes.join_challenge(challenge_id=challenge_id, db=db, user=user)


@router.post("/api/challenges/{challenge_id}/complete")
def dependency_aware_complete(
    challenge_id: int,
    data: ChallengeCompleteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge = db.get(Challenge, challenge_id)
    if challenge:
        require_server_dependencies(db, user, challenge)
    return challenge_routes.complete_challenge(challenge_id=challenge_id, data=data, db=db, user=user)
