from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def register(client,email,username):
    r=client.post('/api/auth/register',json={'email':email,'username':username,'password':'Trending123!'});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_trending_score_uses_verified_participation_not_reviews_or_featured_status():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!');admin=login(client,'admin@demo.nubagz.com','Admin123!')
        participant=register(client,'feature21-participant@example.com','Feature21Participant');observer=register(client,'feature21-observer@example.com','Feature21Observer')
        project=client.post('/api/projects',headers=creator,json={'name':'Feature Twenty One Trending','symbol':'TRD21','description':'An isolated project used to prove trending rank is based on verified participation rather than paid featured placement or reviews.','chain':'Avalanche'});assert project.status_code==200
        pid=project.json()['id'];assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200
        campaign=client.post('/api/campaigns',headers=creator,json={'project_id':pid,'title':'Organic Momentum Bag','description':'A non-featured funded Bag used to prove the real participation trend score formula.','category':'LEARN','difficulty':'EASY','reward_asset':'TRD21','funding_type':'TOKEN','token_allocation':20,'gross_reward_per_user':10,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':2,'featured':False,'challenges':[{'title':'Verify momentum','description':'Answer the verification check for this organic trending pathway.','category':'LEARN','verification_type':'QUIZ','config':{'question':'Token?','options':['TRD21','BTC'],'answer':'TRD21'},'xp_reward':10}]});assert campaign.status_code==200
        cid=campaign.json()['id'];challenge_id=campaign.json()['challenges'][0]['id'];assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':20,'tx_hash':'feature21-funding'}).status_code==200;assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':20,'tx_hash':'feature21-funding'}).status_code==200;assert client.patch(f'/api/admin/campaigns/{cid}',headers=admin,json={'status':'LIVE'}).status_code==200
        assert client.post(f'/api/campaigns/{cid}/enroll',headers=participant).status_code==200
        completed=client.post(f'/api/challenges/{challenge_id}/complete',headers=participant,json={'answer':'TRD21'});assert completed.status_code==200 and completed.json()['completed'] is True
        assert client.post(f'/api/reviews/projects/{pid}',headers=participant,json={'rating':5,'review':'Reviews are retired and must not affect Trending.'}).status_code==410

        trending=client.get('/api/trending?days=7',headers=observer);assert trending.status_code==200
        row=next(b for b in trending.json()['bagz'] if b['campaign_id']==cid)
        assert row['recent_enrollments']==1 and row['recent_completions']==1
        assert row['recent_onchain_verifications']==0 and row['repeat_participants']==0
        assert row['trend_score']==4
        assert 'reviews' not in trending.json()['method'].lower()
        assert 'paid featured placement does not increase' in trending.json()['method'].lower()
