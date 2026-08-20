from fastapi.testclient import TestClient
from app.main import app


def login(client, email, password):
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200
    return {'Authorization': f"Bearer {r.json()['access_token']}"}


def test_bagdrop_requires_admin_activation_and_prevents_double_claim():
    with TestClient(app) as client:
        creator = login(client, 'creator@demo.nubagz.com', 'Creator123!')
        admin = login(client, 'admin@demo.nubagz.com', 'Admin123!')
        earner = login(client, 'demo@demo.nubagz.com', 'Demo123!')
        projects = client.get('/api/projects/mine', headers=creator).json()
        project = next(p for p in projects if p['status'] == 'APPROVED')

        created = client.post('/api/bagdrops', headers=creator, json={
            'project_id': project['id'], 'title': 'Feature Four Drop', 'rarity': 'RARE',
            'max_claims': 1, 'min_bag_score': 0, 'funding_tx_hash': '0xfeature04funding',
            'items': [{'asset': 'DROP4', 'amount_per_claim': 25, 'funded_amount': 25}]
        })
        assert created.status_code == 200
        drop_id = created.json()['id']
        assert created.json()['status'] == 'PENDING'
        assert created.json()['funding_status'] == 'DECLARED'
        assert all(d['id'] != drop_id for d in client.get('/api/bagdrops', headers=earner).json())

        queue = client.get('/api/bagdrops/admin', headers=admin)
        assert queue.status_code == 200
        assert any(d['id'] == drop_id and d['status'] == 'PENDING' for d in queue.json())

        activated = client.post(f'/api/bagdrops/{drop_id}/activate', headers=admin)
        assert activated.status_code == 200
        assert activated.json()['status'] == 'LIVE'
        assert activated.json()['funding_status'] == 'VERIFIED'

        claim = client.post(f'/api/bagdrops/{drop_id}/claim', headers=earner)
        assert claim.status_code == 200
        assert claim.json()['rewards'] == [{'asset': 'DROP4', 'amount': '25.00000000'}]
        assert client.post(f'/api/bagdrops/{drop_id}/claim', headers=earner).status_code == 409

        balances = client.get('/api/users/dashboard', headers=earner).json()['balances']
        assert any(b['asset_symbol'] == 'DROP4' and float(b['amount']) == 25 for b in balances)
