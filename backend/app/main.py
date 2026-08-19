from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .db import Base, engine, SessionLocal
from . import economy_models, risk_models, marketplace_models, engagement_models  # noqa: F401 - registers extension tables
from .seed import seed_demo
from .routers import auth, projects, campaigns, users, admin, funding, earnings, prices, bagdrops, daily, onchain, trust, access, risk, referrals, builders, bounties, revenue_share, recommendations, notifications, project_analytics, templates, reviews, reports


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try: seed_demo(db)
    finally: db.close()
    yield


app = FastAPI(title=settings.app_name, version="1.19.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
for router in (auth,projects,campaigns,users,admin,funding,earnings,prices,bagdrops,daily,onchain,trust,access,risk,referrals,builders,bounties,revenue_share,recommendations,notifications,project_analytics,templates,reviews,reports): app.include_router(router.router)

@app.get("/api/health")
def health(): return {"status":"ok","service":"nubagz-api","version":"1.19.0"}
