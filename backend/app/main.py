from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .db import Base, engine, SessionLocal
from . import economy_models, risk_models, marketplace_models, engagement_models, integration_models, trust_models, challenge_models  # noqa: F401 - registers extension/history tables
from .models import Project, Campaign
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        normalize_legacy_publication_states(db)
        seed_demo(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, version="1.27.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
for router in (auth,projects,campaigns,users,admin,funding,earnings,prices,bagdrops,daily,onchain,trust,access,risk,referrals,bounties,revenue_share,recommendations,notifications,project_analytics,templates,reviews,reports,activity,trending,watchbag,swaps,gas,challenges,creator): app.include_router(router.router)

@app.get("/api/health")
def health(): return {"status":"ok","service":"nubagz-api","version":"1.27.0"}
