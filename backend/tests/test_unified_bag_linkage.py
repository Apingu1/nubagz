from fastapi.testclient import TestClient

from app.main import app


def login(client, email, password):
    response = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200
    return {'Authorization': f"Bearer {response.json()['access_token']}"}


def test_featured_home_bags_are_present_in_unified_bag_work():
    """A Bag visible on Home must never disappear from the Bag Work marketplace."""
    with TestClient(app) as client:
        user = login(client, 'demo@demo.nubagz.com', 'Demo123!')
        featured = client.get('/api/campaigns?featured=true')
        assert featured.status_code == 200
        featured_rows = featured.json()
        assert featured_rows, 'Demo Home should expose at least one featured Bag'

        work = client.get('/api/challenges', headers=user)
        assert work.status_code == 200
        work_rows = work.json()
        campaign_ids = {row['campaign_id'] for row in work_rows}

        for bag in featured_rows:
            assert bag['id'] in campaign_ids, (
                f"Featured Home Bag {bag['id']} ({bag['title']}) is not represented "
                "in the unified Bag Work feed"
            )


def test_full_reward_funding_makes_new_bag_live_and_discoverable_automatically():
    """Funding verification is the publication gate; no hidden second click is required."""
    with TestClient(app) as client:
        creator = login(client, 'creator@demo.nubagz.com', 'Creator123!')
        admin = login(client, 'admin@demo.nubagz.com', 'Admin123!')
        user = login(client, 'demo@demo.nubagz.com', 'Demo123!')

        payload = {
            'project': {
                'name': 'Discoverability Link Test',
                'symbol': 'DLINK',
                'description': 'A project created specifically to verify funded Bag discoverability in the unified Bag Work feed.',
                'website': 'https://example.com/dlink',
                'chain': 'Avalanche',
            },
            'trust': {
                'contract_address': '0x1111111111111111111111111111111111111111',
                'team_url': 'https://example.com/dlink/team',
                'team_verified': True,
            },
            'bag': {
                'project_id': 0,
                'title': 'Discoverable Funded Bag',
                'description': 'This funded Bag should become visible in Bag Work immediately after objective reward funding verification.',
                'category': 'DISCOVER',
                'difficulty': 'EASY',
                'reward_asset': 'DLINK',
                'funding_type': 'TOKEN',
                'token_allocation': 200,
                'gross_reward_per_user': 100,
                'user_share_pct': 80,
                'nubagz_share_pct': 15,
                'referral_share_pct': 5,
                'max_users': 2,
                'missions': [],
                'challenges': [{
                    'title': 'Read the project brief',
                    'description': 'Read the project brief and mark this learning activity complete.',
                    'category': 'LEARN',
                    'verification_type': 'SELF_ATTEST',
                    'config': {},
                    'xp_reward': 20,
                }],
            },
            'min_bag_score': 0,
            'reward_funding': {
                'amount': 200,
                'tx_hash': 'dlink-declared-funding',
            },
        }

        created = client.post('/api/creator/launch', headers=creator, json=payload)
        assert created.status_code == 200
        campaign_id = created.json()['campaign_id']
        assert created.json()['campaign_status'] == 'DRAFT'

        before = client.get('/api/challenges', headers=user)
        assert before.status_code == 200
        assert campaign_id not in {row['campaign_id'] for row in before.json()}

        verified = client.post(
            f'/api/funding/campaigns/{campaign_id}/verify',
            headers=admin,
            json={'amount': 200, 'tx_hash': 'dlink-verified-funding'},
        )
        assert verified.status_code == 200
        assert verified.json()['fully_funded'] is True
        assert verified.json()['campaign_status'] == 'LIVE'
        assert verified.json()['discoverable'] is True

        after = client.get('/api/challenges', headers=user)
        assert after.status_code == 200
        rows = [row for row in after.json() if row['campaign_id'] == campaign_id]
        assert len(rows) == 1
        assert rows[0]['title'] == 'Read the project brief'
