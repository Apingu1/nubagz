from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_recommendations_are_explainable_sorted_and_never_override_access():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        earner=login(client,'demo@demo.nubagz.com','Demo123!')

        baseline=client.get('/api/recommendations/me',headers=earner)
        assert baseline.status_code==200
        baseline_payload=baseline.json()
        assert baseline_payload['recommendations']
        target_id=baseline_payload['recommendations'][0]['campaign_id']

        assert client.post(f"/api/access/campaigns/{target_id}",headers=creator,json={'min_bag_score':1000}).status_code==200
        response=client.get('/api/recommendations/me',headers=earner)
        assert response.status_code==200
        payload=response.json()
        assert payload['restricted'] is False
        assert 'verified funding' in payload['method'].lower()
        ids=[r['campaign_id'] for r in payload['recommendations']]
        assert target_id not in ids
        scores=[r['recommendation_score'] for r in payload['recommendations']]
        assert scores==sorted(scores,reverse=True)
        assert all(r['reasons'] for r in payload['recommendations'])
        assert all(any('reward inventory' in reason.lower() for reason in r['reasons']) for r in payload['recommendations'])
        assert all(0 <= r['project_trust_score'] <= 100 for r in payload['recommendations'])

        assert client.post(f"/api/access/campaigns/{target_id}",headers=creator,json={'min_bag_score':0}).status_code==200
        restored=client.get('/api/recommendations/me',headers=earner)
        assert restored.status_code==200
        assert any(r['campaign_id']==target_id for r in restored.json()['recommendations'])
