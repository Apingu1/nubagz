from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Project, Campaign, Enrollment
from ..engagement_models import ProjectReview

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    review: str = Field(min_length=10, max_length=3000)


def eligible(db: Session, user: User, project: Project) -> bool:
    if project.owner_id == user.id:
        return False
    return db.query(Enrollment.id).join(Campaign, Campaign.id == Enrollment.campaign_id).filter(Enrollment.user_id == user.id, Enrollment.status == "COMPLETED", Campaign.project_id == project.id).first() is not None


def review_payload(row: ProjectReview, db: Session):
    user = db.get(User, row.user_id)
    return {"id":row.id,"user_id":row.user_id,"username":user.username if user else "Unknown","rating":row.rating,"review":row.review,"status":row.status,"created_at":row.created_at.isoformat(),"updated_at":row.updated_at.isoformat(),"verified_participant":True}


def summary(project: Project, db: Session, user: User):
    rows = db.query(ProjectReview).filter(ProjectReview.project_id == project.id, ProjectReview.status == "PUBLISHED").order_by(ProjectReview.updated_at.desc()).all()
    avg = (sum(Decimal(row.rating) for row in rows) / Decimal(len(rows))) if rows else Decimal("0")
    mine_any = db.query(ProjectReview).filter(ProjectReview.project_id == project.id, ProjectReview.user_id == user.id).first()
    mine = mine_any if mine_any and mine_any.status == "PUBLISHED" else None
    hidden_by_moderation = bool(mine_any and mine_any.status == "HIDDEN")
    return {"project_id":project.id,"name":project.name,"symbol":project.symbol,"average_rating":str(avg.quantize(Decimal('0.01'))),"review_count":len(rows),"eligible_to_review":eligible(db,user,project) and not hidden_by_moderation,"my_review":review_payload(mine,db) if mine else None,"my_review_status":mine_any.status if mine_any else None,"reviews":[review_payload(row,db) for row in rows[:50]],"disclaimer":"Ratings describe verified participants' NuBagz experience. They are not investment advice or a safety guarantee. Moderation-hidden reviews cannot be republished by editing them."}


@router.get("/projects")
def project_summaries(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    projects = db.query(Project).filter(Project.status == "APPROVED").order_by(Project.created_at.desc()).all()
    return [summary(project, db, user) for project in projects]


@router.get("/projects/{project_id}")
def project_reviews(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = db.get(Project, project_id)
    if not project or project.status != "APPROVED":
        raise HTTPException(404, "Approved project not found")
    return summary(project, db, user)


@router.post("/projects/{project_id}")
def write_review(project_id: int, data: ReviewIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = db.get(Project, project_id)
    if not project or project.status != "APPROVED":
        raise HTTPException(404, "Approved project not found")
    if project.owner_id == user.id:
        raise HTTPException(403, "Project owners cannot review their own project")
    if not eligible(db, user, project):
        raise HTTPException(403, "Complete a funded campaign for this project before reviewing your participant experience")
    row = db.query(ProjectReview).filter(ProjectReview.project_id == project.id, ProjectReview.user_id == user.id).first()
    if row and row.status == "HIDDEN":
        raise HTTPException(409, "This review was hidden by moderation and cannot be republished through a normal edit")
    if not row:
        row = ProjectReview(project_id=project.id, user_id=user.id, rating=data.rating, review=data.review)
        db.add(row)
    else:
        row.rating = data.rating; row.review = data.review
    db.commit(); db.refresh(row)
    return review_payload(row, db)
