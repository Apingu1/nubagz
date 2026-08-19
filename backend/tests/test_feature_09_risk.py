from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_duplicate_payout_signal_and_restriction_enforcement():
    with TestClient(app) as client:
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        a=client.post('/api/auth/register',json={'email':'risk-a@example.com','username':'RiskAUser','password':'RiskPass123!'})
        b=client.post('/api/auth/register',json={'email':'risk-b@example.com','username':'RiskBUser','password':'RiskPass123!'})
        assert a.status_code==200 and b.status_code==200
        ah={'Authorization':f"Bearer {a.json()['access_token']}"};bh={'Authorization':f"Bearer {b.json()['access_token']}"}
        address='0x9999999999999999999999999999999999999999'
        assert client.post('/api/users/payout-addresses',headers=ah,json={'address':address,'chain':'Avalanche','label':'Wallet A','make_primary':True}).status_code==200
        assert client.post('/api/users/payout-addresses',headers=bh,json={'address':address,'chain':'Avalanche','label':'Wallet B','make_primary':True}).status_code==200
        risk=client.post('/api/risk/evaluate',headers=bh)
        assert risk.status_code==200
        assert risk.json()['risk_score']>=30
        assert risk.json()['trust_level']=='REVIEW'
        assert any(s['type']=='SHARED_PAYOUT_ADDRESS' for s in risk.json()['signals'])

        restricted=client.post(f"/api/risk/users/{b.json()['user']['id']}/trust",headers=admin,json={'trust_level':'RESTRICTED'})
        assert restricted.status_code==200
        target=next(c for c in client.get('/api/campaigns/mine',headers=creator).json() if c['status']=='LIVE')
        blocked=client.post(f"/api/campaigns/{target['id']}/enroll",headers=bh)
        assert blocked.status_code==403 and 'restricted' in blocked.json()['detail'].lower()
        daily=client.get('/api/daily/earn',headers=bh)
        assert daily.status_code==200 and daily.json()['restricted'] is True and daily.json()['opportunity_count']==0

        project=next(p for p in client.get('/api/projects/mine',headers=creator).json() if p['status']=='APPROVED')
        drop=client.post('/api/bagdrops',headers=creator,json={'project_id':project['id'],'title':'Risk Gated Drop','rarity':'COMMON','max_claims':2,'min_bag_score':0,'funding_tx_hash':'risk-drop-funding','items':[{'asset':'RISK','amount_per_claim':1,'funded_amount':2}]})
        assert drop.status_code==200
        assert client.post(f"/api/bagdrops/{drop.json()['id']}/activate",headers=admin).status_code==200
        blocked_drop=client.post(f"/api/bagdrops/{drop.json()['id']}/claim",headers=bh)
        assert blocked_drop.status_code==403 and 'restricted' in blocked_drop.json()['detail'].lower()
