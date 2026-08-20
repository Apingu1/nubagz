from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def register(client,email,username):
    r=client.post('/api/auth/register',json={'email':email,'username':username,'password':'WatchBag123!'});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_watchbag_only_saves_live_funded_bagz_and_is_idempotent():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!');admin=login(client,'admin@demo.nubagz.com','Admin123!');user=register(client,'feature22-user@example.com','Feature22Watcher')
        project=client.post('/api/projects',headers=creator,json={'name':'Feature Twenty Two WatchBag','symbol':'WTCH22','description':'An isolated project used to prove WatchBag saves only live funded public opportunities.','chain':'Avalanche'});assert project.status_code==200
        pid=project.json()['id'];assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200
        pending=client.post('/api/campaigns',headers=creator,json={'project_id':pid,'title':'Pending Watch Attempt','description':'This campaign remains pending and must not be watchable before verified funding and activation.','category':'LEARN','difficulty':'EASY','reward_asset':'WTCH22','funding_type':'TOKEN','token_allocation':10,'gross_reward_per_user':10,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':1,'missions':[{'title':'Pending','description':'Pending mission','mission_type':'LEARN','verification_type':'SELF_ATTEST','xp_reward':10}]});assert pending.status_code==200
        assert client.post(f"/api/watchbag/{pending.json()['id']}",headers=user).status_code==409

        cid=pending.json()['id'];assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':10,'tx_hash':'feature22-funding'}).status_code==200;assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':10,'tx_hash':'feature22-funding'}).status_code==200;assert client.patch(f'/api/admin/campaigns/{cid}',headers=admin,json={'status':'LIVE'}).status_code==200
        first=client.post(f'/api/watchbag/{cid}',headers=user);assert first.status_code==200
        second=client.post(f'/api/watchbag/{cid}',headers=user);assert second.status_code==200 and second.json()['id']==first.json()['id']
        status=client.get(f'/api/watchbag/status/{cid}',headers=user).json();assert status['watched'] is True and status['watchable'] is True
        listing=client.get('/api/watchbag',headers=user);assert listing.status_code==200
        rows=[r for r in listing.json() if r['campaign_id']==cid];assert len(rows)==1 and rows[0]['spots_left']==1 and rows[0]['watchable'] is True
        assert client.delete(f'/api/watchbag/{cid}',headers=user).status_code==200
        assert client.get(f'/api/watchbag/status/{cid}',headers=user).json()['watched'] is False
