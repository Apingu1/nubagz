from fastapi.testclient import TestClient
from app.main import app


def login(client, email, password):
    res=client.post('/api/auth/login',json={'email':email,'password':password})
    assert res.status_code==200
    return {'Authorization':f"Bearer {res.json()['access_token']}"}


def test_bagscore_tiers_and_campaign_gate():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        earner=login(client,'demo@demo.nubagz.com','Demo123!')
        profile=client.get('/api/access/me',headers=earner)
        assert profile.status_code==200
        assert profile.json()['tier'] in {'STARTER','EXPLORER','CONTRIBUTOR','PREMIUM','ELITE'}

        campaigns=client.get('/api/campaigns/mine',headers=creator).json()
        target=next(c for c in campaigns if c['status']=='LIVE' and c['title']!='Test Participation Bag')
        gate=client.post(f"/api/access/campaigns/{target['id']}",headers=creator,json={'min_bag_score':1000})
        assert gate.status_code==200
        blocked=client.post(f"/api/campaigns/{target['id']}/enroll",headers=earner)
        assert blocked.status_code==403
        assert 'BagScore 1000+' in blocked.json()['detail']
        reset=client.post(f"/api/access/campaigns/{target['id']}",headers=creator,json={'min_bag_score':0})
        assert reset.status_code==200
