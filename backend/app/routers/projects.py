from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Project
from ..schemas import ProjectCreate, ProjectOut
from ..utils import slugify

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).filter(Project.status == "APPROVED").order_by(Project.created_at.desc()).all()


@router.get("/mine", response_model=list[ProjectOut])
def my_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Project).filter(Project.owner_id == user.id).order_by(Project.created_at.desc()).all()


@router.post("", response_model=ProjectOut)
def create_project(data: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    base = slugify(data.name)
    slug = base
    i = 2
    while db.query(Project).filter(Project.slug == slug).first():
        slug = f"{base}-{i}"
        i += 1
    project = Project(owner_id=user.id, slug=slug, **data.model_dump())
    db.add(project)
    if user.role == "USER":
        user.role = "CREATOR"
    db.commit()
    db.refresh(project)
    return project


@router.get("/{slug}", response_model=ProjectOut)
def get_project(slug: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.slug == slug).first()
    if not project:
        raise HTTPException(404, "Project not found")
    return project
