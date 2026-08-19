from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .db import Base, engine, SessionLocal
from .seed import seed_demo
from .routers import auth, projects, campaigns, users, admin


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(campaigns.router)
app.include_router(users.router)
app.include_router(admin.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "nubagz-api", "version": "1.0.0"}
