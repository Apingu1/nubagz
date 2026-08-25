from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Project
from ..schemas import ProjectCreate, ProjectOut
from ..utils import slugify

router = APIRouter(prefix="/api/projects", tags=["projects"])
PUBLIC_PROJECT_STATUSES = {"LIVE", "APPROVED"}  # APPROVED retained for legacy records.


class ProjectProfileUpdate(BaseModel):
    website: str | None = Field(default=None, max_length=255)
    treasury_address: str | None = Field(default=None, max_length=255)
    logo_url: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, min_length=20, max_length=5000)


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).filter(Project.status.in_(PUBLIC_PROJECT_STATUSES)).order_by(Project.created_at.desc()).all()


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
    # Projects publish without a NuBagz endorsement gate. Project Trust and moderation
    # communicate risk; administrators can suspend content when necessary.
    project = Project(owner_id=user.id, slug=slug, status="LIVE", **data.model_dump())
    db.add(project)
    if user.role == "USER":
        user.role = "CREATOR"
    db.commit()
    db.refresh(project)
    return project


@router.patch("/{project_id}/profile")
def update_project_profile(project_id: int, data: ProjectProfileUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = db.get(Project, project_id)
    if not project or (project.owner_id != user.id and user.role != "ADMIN"):
        raise HTTPException(403, "You do not manage this project")
    if project.status in {"SUSPENDED", "ARCHIVED"} and user.role != "ADMIN":
        raise HTTPException(409, "Suspended or archived projects cannot be edited by the creator")
    values = data.model_dump(exclude_unset=True)
    for key, value in values.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return {
        "id": project.id,
        "website": project.website,
        "treasury_address": project.treasury_address,
        "logo_url": project.logo_url,
        "description": project.description,
    }


@router.get("/{slug}", response_model=ProjectOut)
def get_project(slug: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.slug == slug).first()
    if not project or project.status == "SUSPENDED":
        raise HTTPException(404, "Project not found")
    return project
