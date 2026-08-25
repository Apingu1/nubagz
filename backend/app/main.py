from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .db import Base, engine, SessionLocal
from . import economy_models, risk_models, marketplace_models, engagement_models, integration_models, trust_models, challenge_models  # noqa: F401 - registers extension/history tables
from .models import Project, Campaign, Mission, MissionCompletion
from .challenge_models import Challenge, ChallengeCompletion
from .seed import seed_demo
from .routers import auth, projects, campaigns, users, admin, funding, earnings, prices, bagdrops, daily, onchain, trust, access, risk, referrals, bounties, revenue_share, recommendations, notifications, project_analytics, templates, reviews, reports, activity, trending, watchbag, swaps, gas, challenges, creator


def normalize_legacy_publication_states(db):
    """One-way compatibility mapping from the old approval workflow.

    Pending projects no longer need NuBagz endorsement, so they become LIVE.
    Pending Bags become creator-controlled DRAFTs. Previously rejected content
    remains non-public by mapping to SUSPENDED rather than being republished.
    """
    db.query(Project).filter(Project.status == "PENDING").update({"status": "LIVE"}, synchronize_session=False)
    db.query(Project).filter(Project.status == "REJECTED").update({"status": "SUSPENDED"}, synchronize_session=False)
    db.query(Campaign).filter(Campaign.status == "PENDING").update({"status": "DRAFT"}, synchronize_session=False)
    db.query(Campaign).filter(Campaign.status == "REJECTED").update({"status": "SUSPENDED"}, synchronize_session=False)
    db.commit()


def backfill_legacy_missions_to_challenges(db):
    """Make every legacy Mission-only Bag visible in the unified Bag Work feed.

    Campaign remains the funded reward container, but Challenge is now the one
    user-facing activity model. Older databases (and the original demo seed)
    can contain LIVE Campaigns with Missions and no Challenge rows, which made
    Home show a Bag while Bag Work showed nothing. This migration is idempotent:
    only Campaigns with zero Challenge rows are converted, legacy Mission rows
    remain untouched for backwards compatibility, and existing MissionCompletion
    records are mirrored so a user's historical progress is not reset.
    """
    category_map = {
        "LEARN": "LEARN",
        "CREATE": "CONTENT",
        "CONTENT": "CONTENT",
        "COMMUNITY": "COMMUNITY",
        "SOCIAL": "SOCIAL",
        "ONCHAIN": "ONCHAIN",
    }
    allowed_verification = {"SELF_ATTEST", "PROJECT_REVIEW", "QUIZ"}

    campaigns = db.query(Campaign).all()
    changed = False
    for campaign in campaigns:
        if db.query(Challenge.id).filter(Challenge.campaign_id == campaign.id).first():
            continue
        missions = db.query(Mission).filter(Mission.campaign_id == campaign.id).order_by(Mission.position).all()
        if not missions:
            continue

        challenge_by_mission = {}
        for mission in missions:
            verification = (mission.verification_type or "SELF_ATTEST").upper()
            if verification not in allowed_verification:
                verification = "SELF_ATTEST"
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
            legacy_completions = db.query(MissionCompletion).filter(MissionCompletion.mission_id.in_(mission_ids)).all()
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
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        normalize_legacy_publication_states(db)
        seed_demo(db)
        backfill_legacy_missions_to_challenges(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, version="1.28.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
for router in (auth,projects,campaigns,users,admin,funding,earnings,prices,bagdrops,daily,onchain,trust,access,risk,referrals,bounties,revenue_share,recommendations,notifications,project_analytics,templates,reviews,reports,activity,trending,watchbag,swaps,gas,challenges,creator): app.include_router(router.router)

@app.get("/api/health")
def health(): return {"status":"ok","service":"nubagz-api","version":"1.28.0"}
