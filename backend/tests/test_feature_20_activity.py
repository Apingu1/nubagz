from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def register(client,email,username):
    r=client.post('/api/auth/register',json={'email':email,'username':username,'password':'Activity123!'});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_activity_feed_contains_real_completion_without_private_account_fields():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!');admin=login(client,'admin@demo.nubagz.com','Admin123!')
        worker=register(client,'feature20-worker@example.com','Feature20Worker')
        project=client.post('/api/projects',headers=creator,json={'name':'Feature Twenty Activity','symbol':'ACT20','description':'An isolated project used to prove community activity is based on real participation and privacy safe.','chain':'Avalanche'});assert project.status_code==200
        pid=project.json()['id'];assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200
        campaign=client.post('/api/campaigns',headers=creator,json={'project_id':pid,'title':'Authentic Activity Bag','description':'Complete this funded Bag to generate a real privacy-safe community activity event.','category':'LEARN','difficulty':'EASY','reward_asset':'ACT20','funding_type':'TOKEN','token_allocation':10,'gross_reward_per_user':10,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':1,'missions':[{'title':'Complete','description':'Complete the authentic activity pathway','mission_type':'LEARN','verification_type':'SELF_ATTEST','xp_reward':10}]});assert campaign.status_code==200
        cid=campaign.json()['id'];assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':10,'tx_hash':'feature20-funding'}).status_code==200;assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':10,'tx_hash':'feature20-funding'}).status_code==200;assert client.patch(f'/api/admin/campaigns/{cid}',headers=admin,json={'status':'LIVE'}).status_code==200
        assert client.post(f'/api/campaigns/{cid}/enroll',headers=worker).status_code==200;mission=client.get(f'/api/campaigns/{cid}').json()['missions'][0];assert client.post(f"/api/campaigns/{cid}/missions/{mission['id']}/complete",headers=worker,json={'answer':None}).status_code==200
        feed=client.get('/api/activity?limit=100',headers=worker);assert feed.status_code==200
        event=next(e for e in feed.json()['events'] if e['event_type']=='BAG_COMPLETED' and e['username']=='Feature20Worker' and e['campaign_id']==cid)
        assert event['project_name']=='Feature Twenty Activity'
        assert set(event)=={'event_type','username','headline','detail','project_name','campaign_id','link_path','occurred_at'}
        event_payload=str(feed.json()['events']).lower()
        for forbidden in ('feature20-worker@example.com','wallet_address','payout_address','payout_destination','account_balance'):
            assert forbidden not in event_payload
        privacy=feed.json()['privacy'].lower()
        assert 'never exposes emails' in privacy and 'wallet addresses' in privacy and 'payout destinations' in privacy and 'private account balances' in privacy
