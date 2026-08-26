from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.engagement_models import ProjectReview
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_public_reviews_are_retired_while_historical_rows_are_preserved():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        project=client.get('/api/projects/mine',headers=creator).json()[0]
        pid=project['id']

        db=SessionLocal()
        try:
            historical=ProjectReview(
                project_id=pid,
                user_id=1,
                rating=4,
                review='Historical review retained only for audit and old moderation references.',
                status='VISIBLE',
            )
            db.add(historical);db.commit();db.refresh(historical);review_id=historical.id
        finally:
            db.close()

        listing=client.get(f'/api/reviews/projects/{pid}',headers=creator)
        assert listing.status_code==410
        assert 'retired' in listing.json()['detail'].lower()
        posting=client.post(f'/api/reviews/projects/{pid}',headers=creator,json={'rating':5,'review':'New public reviews must remain disabled.'})
        assert posting.status_code==410
        summaries=client.get('/api/reviews/projects',headers=creator)
        assert summaries.status_code==410

        db=SessionLocal()
        try:
            row=db.get(ProjectReview,review_id)
            assert row is not None
            assert row.review.startswith('Historical review retained')
        finally:
            db.close()
