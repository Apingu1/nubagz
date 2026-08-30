from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from . import admin_security_models, admin_user_models, challenge_models, economy_models, engagement_models, integration_models, marketplace_models, risk_models, security_models, trust_models  # noqa: F401
from .bag_lifecycle import reconcile_verified_drafts
from .challenge_models import Challenge, ChallengeCompletion
from .config import settings
from .db import Base, SessionLocal, engine
from .models import Campaign, Mission, MissionCompletion, Project
from .routers import access, activity, admin, admin_security, admin_users, auth, bagdrops, bounties, campaigns, challenges, creator, daily, dependency_security, domain_v2, earnings, funding, gas, gas_security, notifications, onchain, prices, project_analytics, projects, recommendations, referrals, reports, revenue_share, reviews, risk, swaps, templates, trending, trust, users, watchbag
from .seed import seed_demo


def ensure_runtime_schema():
    """Apply tiny additive compatibility upgrades to existing local databases."""
    inspector = inspect(engine)
    if "project_trust_evidence" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("project_trust_evidence")}
    if "team_url" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE project_trust_evidence ADD COLUMN team_url VARCHAR(500)"))


def normalize_legacy_publication_states(db):
    db.query(Project).filter(Project.status == "PENDING").update({"status": "LIVE"}, synchronize_session=False)
    db.query(Project).filter(Project.status == "REJECTED").update({"status": "SUSPENDED"}, synchronize_session=False)
    db.query(Campaign).filter(Campaign.status == "PENDING").update({"status": "DRAFT"}, synchronize_session=False)
    db.query(Campaign).filter(Campaign.status == "REJECTED").update({"status": "SUSPENDED"}, synchronize_session=False)
    db.commit()


def normalize_legacy_challenge_verification(db):
    """Remove the old one-click verification type from any existing draft data."""
    changed = db.query(Challenge).filter(Challenge.verification_type == "SELF_ATTEST").update(
        {"verification_type": "PROJECT_REVIEW"},
        synchronize_session=False,
    )
    if changed:
        db.commit()


def backfill_legacy_missions_to_challenges(db):
    """Convert Mission-only Bags to the unified Challenge model once.

    Old one-click Mission verification is intentionally upgraded to PROJECT_REVIEW.
    Historical verified completions are mirrored so already-earned history is not
    rewritten, while any unfinished work now uses the current evidence path.
    """
    category_map = {
        "LEARN": "LEARN",
        "CREATE": "CONTENT",
        "CONTENT": "CONTENT",
        "COMMUNITY": "COMMUNITY",
        "SOCIAL": "SOCIAL",
        "ONCHAIN": "ONCHAIN",
    }

    campaigns = db.query(Campaign).all()
    changed = False
    for campaign in campaigns:
        if db.query(Challenge.id).filter(Challenge.campaign_id == campaign.id).first():
            continue
        missions = db.query(Mission).filter(
            Mission.campaign_id == campaign.id
        ).order_by(Mission.position).all()
        if not missions:
            continue

        challenge_by_mission = {}
        for mission in missions:
            legacy_verification = (mission.verification_type or "").upper()
            verification = "QUIZ" if legacy_verification == "QUIZ" else "PROJECT_REVIEW"
            category = category_map.get((mission.mission_type or "").upper(), "BAG_WORK")
            config = {"legacy_mission_id": mission.id}
            if verification == "QUIZ":
                config.update({
                    "question": mission.quiz_question or "Answer the question to continue",
                    "options": mission.quiz_options or [],
                    "answer": mission.quiz_answer or "",
                })
            challenge = Challenge(
                campaign_id=campaign.id,
                title=mission.title,
                description=mission.description or "",
                category=category,
                verification_type=verification,
                target_url=mission.target_url,
                config=config,
                xp_reward=mission.xp_reward,
                position=mission.position,
                status="ACTIVE",
                created_at=campaign.created_at,
            )
            db.add(challenge)
            db.flush()
            challenge_by_mission[mission.id] = challenge

        mission_ids = list(challenge_by_mission)
        if mission_ids:
            legacy_completions = db.query(MissionCompletion).filter(
                MissionCompletion.mission_id.in_(mission_ids)
            ).all()
            for completion in legacy_completions:
                challenge = challenge_by_mission.get(completion.mission_id)
                if not challenge:
                    continue
                exists = db.query(ChallengeCompletion.id).filter(
                    ChallengeCompletion.user_id == completion.user_id,
                    ChallengeCompletion.challenge_id == challenge.id,
                ).first()
                if exists:
                    continue
                status = "VERIFIED" if completion.verified else "PENDING"
                db.add(ChallengeCompletion(
                    user_id=completion.user_id,
                    challenge_id=challenge.id,
                    status=status,
                    answer=completion.answer,
                    evidence={"migrated_from_legacy_mission": completion.mission_id},
                    submitted_at=completion.completed_at,
                    verified_at=completion.completed_at if completion.verified else None,
                    completed_at=completion.completed_at if completion.verified else None,
                ))
        changed = True

    if changed:
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_runtime_security()
    Base.metadata.create_all(bind=engine)
    ensure_runtime_schema()
    db = SessionLocal()
    try:
        normalize_legacy_publication_states(db)
        seed_demo(db)
        normalize_legacy_challenge_verification(db)
        backfill_legacy_missions_to_challenges(db)
        reconcile_verified_drafts(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, version="1.33.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for router in (
    auth, projects, campaigns, users, admin, admin_security, admin_users, funding, earnings, prices, bagdrops,
    daily, onchain, trust, access, risk, referrals, bounties, revenue_share,
    recommendations, notifications, project_analytics, templates, reviews, reports,
    activity, trending, watchbag, swaps, gas_security, gas, dependency_security, challenges, domain_v2, creator,
):
    app.include_router(router.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "nubagz-api", "version": "1.33.0"}