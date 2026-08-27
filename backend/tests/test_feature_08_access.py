from fastapi.testclient import TestClient
from app.main import app


def login(client, email, password):
    res = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert res.status_code == 200
    return {'Authorization': f"Bearer {res.json()['access_token']}"}


def test_bagscore_tiers_expose_benefits_and_gate_isolated_challenge_bag_enrollments():
    with TestClient(app) as client:
        creator = login(client, 'creator@demo.nubagz.com', 'Creator123!')
        admin = login(client, 'admin@demo.nubagz.com', 'Admin123!')
        earner = login(client, 'demo@demo.nubagz.com', 'Demo123!')

        tiers = client.get('/api/access/tiers')
        assert tiers.status_code == 200
        assert [row['name'] for row in tiers.json()['tiers']] == ['STARTER', 'EXPLORER', 'CONTRIBUTOR', 'PREMIUM', 'ELITE']
        assert 'deposited wealth' in tiers.json()['principle']

        profile = client.get('/api/access/me', headers=earner)
        assert profile.status_code == 200
        assert profile.json()['bag_score'] == 485
        assert profile.json()['tier'] == 'CONTRIBUTOR'
        assert profile.json()['next_tier'] == 'PREMIUM'
        assert profile.json()['next_tier_score'] == 600
        assert profile.json()['points_to_next'] == 115
        assert 'Creator and bounty opportunities' in profile.json()['benefits']

        project = client.post('/api/projects', headers=creator, json={
            'name': 'Feature Eight Access Isolation', 'symbol': 'ACC08',
            'description': 'An isolated funded Bag used only to prove BagScore access gating without shared fixture capacity.',
            'chain': 'Robinhood'
        })
        assert project.status_code == 200
        bag = client.post('/api/campaigns', headers=creator, json={
            'project_id': project.json()['id'], 'title': 'Access Gate Challenge Bag',
            'description': 'A small isolated Challenge-based Bag with enough reward inventory for deterministic access tests.',
            'category': 'LEARN', 'difficulty': 'EASY', 'reward_asset': 'ACC08', 'funding_type': 'TOKEN',
            'token_allocation': 10, 'gross_reward_per_user': 1, 'user_share_pct': 80, 'nubagz_share_pct': 15,
            'referral_share_pct': 5, 'max_users': 10, 'missions': [],
            'challenges': [{
                'title': 'Access proof quiz', 'description': 'A deterministic quiz Challenge used only to make this Bag publishable.',
                'category': 'LEARN', 'verification_type': 'QUIZ', 'config': {'answer': 'access'}, 'xp_reward': 1
            }]
        })
        assert bag.status_code == 200
        target = bag.json()
        assert client.post(f"/api/funding/campaigns/{target['id']}/declare", headers=creator, json={'amount': 10, 'tx_hash': 'feature08-funding'}).status_code == 200
        assert client.post(f"/api/funding/campaigns/{target['id']}/verify", headers=admin, json={'amount': 10, 'tx_hash': 'feature08-funding'}).status_code == 200
        assert client.post(f"/api/campaigns/{target['id']}/publish", headers=creator).status_code == 200

        gate = client.post(f"/api/access/campaigns/{target['id']}", headers=creator, json={'min_bag_score': 600})
        assert gate.status_code == 200
        assert gate.json()['required_tier'] == 'PREMIUM'
        assert gate.json()['message'].startswith('BagScore gate applies to new enrollments')

        access = client.get(f"/api/access/campaigns/{target['id']}", headers=earner)
        assert access.status_code == 200
        assert access.json()['eligible'] is False
        assert access.json()['min_bag_score'] == 600
        assert access.json()['required_tier'] == 'PREMIUM'
        assert access.json()['your_tier'] == 'CONTRIBUTOR'
        assert access.json()['shortfall'] == 115
        assert '115 more points' in access.json()['reason']

        created = client.post('/api/auth/register', json={
            'email': 'feature08-new@example.com', 'username': 'Feature08New', 'password': 'Access123!'
        })
        assert created.status_code == 200
        fresh = {'Authorization': f"Bearer {created.json()['access_token']}"}
        fresh_profile = client.get('/api/access/me', headers=fresh).json()
        assert fresh_profile['tier'] == 'STARTER'
        assert fresh_profile['bag_score'] == 100

        blocked = client.post(f"/api/campaigns/{target['id']}/enroll", headers=fresh)
        assert blocked.status_code == 403
        assert 'BagScore 600+' in blocked.json()['detail']

        reset = client.post(f"/api/access/campaigns/{target['id']}", headers=creator, json={'min_bag_score': 0})
        assert reset.status_code == 200
        open_access = client.get(f"/api/access/campaigns/{target['id']}", headers=fresh).json()
        assert open_access['eligible'] is True
        assert open_access['shortfall'] == 0
        assert open_access['reason'] is None
        enrolled = client.post(f"/api/campaigns/{target['id']}/enroll", headers=fresh)
        assert enrolled.status_code == 200
