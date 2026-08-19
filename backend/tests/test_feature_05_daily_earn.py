from fastapi.testclient import TestClient
from app.main import app


def login(client, email, password):
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200
    return {'Authorization': f"Bearer {r.json()['access_token']}"}


def test_daily_earn_only_lists_eligible_funded_opportunities():
    with TestClient(app) as client:
        creator = login(client, 'creator@demo.nubagz.com', 'Creator123!')
        earner = login(client, 'demo@demo.nubagz.com', 'Demo123!')
        campaigns = client.get('/api/campaigns/mine', headers=creator).json()
        target = campaigns[0]

        locked = client.post(f"/api/access/campaigns/{target['id']}", headers=creator, json={'min_bag_score': 999})
        assert locked.status_code == 200
        daily = client.get('/api/daily/earn', headers=earner)
        assert daily.status_code == 200
        payload = daily.json()
        assert payload['restricted'] is False
        assert payload['opportunity_count'] == len(payload['opportunities'])
        assert all(item['id'] != target['id'] or item['type'] != 'CAMPAIGN' for item in payload['opportunities'])
        assert all(item['reward'] for item in payload['opportunities'])

        restored = client.post(f"/api/access/campaigns/{target['id']}", headers=creator, json={'min_bag_score': 0})
        assert restored.status_code == 200
