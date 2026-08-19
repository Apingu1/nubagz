from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def register(client,email,username):
    r=client.post('/api/auth/register',json={'email':email,'username':username,'password':'Reviews123!'});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_reviews_require_completed_participation_and_are_one_per_user_project():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!');admin=login(client,'admin@demo.nubagz.com','Admin123!')
        participant=register(client,'feature18-p@example.com','Feature18Participant');outsider=register(client,'feature18-o@example.com','Feature18Outsider')
        project=client.post('/api/projects',headers=creator,json={'name':'Feature Eighteen Reviews','symbol':'REV18','description':'An isolated project used to prove reviews come only from verified completed participants.','chain':'Avalanche'});assert project.status_code==200
        pid=project.json()['id'];assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200
        assert client.post(f'/api/reviews/projects/{pid}',headers=creator,json={'rating':5,'review':'Owner should never be allowed to review this project.'}).status_code==403
        assert client.post(f'/api/reviews/projects/{pid}',headers=outsider,json={'rating':5,'review':'Fresh accounts should not be able to create ratings.'}).status_code==403
        campaign=client.post('/api/campaigns',headers=creator,json={'project_id':pid,'title':'Verified Review Bag','description':'Complete this funded Bag before becoming eligible to review the project experience.','category':'LEARN','difficulty':'EASY','reward_asset':'REV18','funding_type':'TOKEN','token_allocation':10,'gross_reward_per_user':10,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':1,'missions':[{'title':'Qualify','description':'Complete the participant pathway','mission_type':'LEARN','verification_type':'SELF_ATTEST','xp_reward':10}]});assert campaign.status_code==200
        cid=campaign.json()['id'];assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':10,'tx_hash':'feature18-funding'}).status_code==200;assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':10,'tx_hash':'feature18-funding'}).status_code==200;assert client.patch(f'/api/admin/campaigns/{cid}',headers=admin,json={'status':'LIVE'}).status_code==200
        assert client.post(f'/api/campaigns/{cid}/enroll',headers=participant).status_code==200;mission=client.get(f'/api/campaigns/{cid}').json()['missions'][0];assert client.post(f"/api/campaigns/{cid}/missions/{mission['id']}/complete",headers=participant,json={'answer':None}).status_code==200
        first=client.post(f'/api/reviews/projects/{pid}',headers=participant,json={'rating':4,'review':'Clear funded onboarding experience with useful project context.'});assert first.status_code==200
        summary=client.get(f'/api/reviews/projects/{pid}',headers=participant).json();assert summary['review_count']==1 and float(summary['average_rating'])==4 and summary['eligible_to_review'] is True
        updated=client.post(f'/api/reviews/projects/{pid}',headers=participant,json={'rating':5,'review':'Updated after review: the participant flow was clear and transparent.'});assert updated.status_code==200
        summary=client.get(f'/api/reviews/projects/{pid}',headers=participant).json();assert summary['review_count']==1 and float(summary['average_rating'])==5 and summary['reviews'][0]['verified_participant'] is True
