from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/reviews", tags=["reviews-retired"])


def retired():
    raise HTTPException(
        410,
        "Public project Reviews are retired. Historical review rows are retained for audit and historical moderation records, but new reviews and public review feeds are disabled.",
    )


@router.get("/projects")
def project_summaries():
    return retired()


@router.get("/projects/{project_id}")
def project_reviews(project_id: int):
    return retired()


@router.post("/projects/{project_id}")
def write_review(project_id: int):
    return retired()
