from fastapi.testclient import TestClient

from app.main import app


def login(client, email, password):
    response = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200
    return {'Authorization': f"Bearer {response.json()['access_token']}"}


def register(client, email, username):
    response = client.post('/api/auth/register', json={
        'email': email,
        'username': username,
        'password': 'Phase1Domain123!',
    })
    assert response.status_code == 200
    return {'Authorization': f"Bearer {response.json()['access_token']}"}


def test_phase1_canonical_project_challenge_create_list_detail_and_join():
    with TestClient(app) as client:
        creator = login(client, 'creator@demo.nubagz.com', 'Creator123!')
        admin = login(client, 'admin@demo.nubagz.com', 'Admin123!')

        project = client.post('/api/projects', headers=creator, json={
            'name': 'Phase One Canonical Project',
            'symbol': 'P1CAN',
            'description': 'A project created specifically to validate the NuBagz V2 Project to Challenge domain surface.',
            'website': 'https://example.com/phase-one',
            'chain': 'Avalanche',
        })
        assert project.status_code == 200
        project_id = project.json()['id']

        created = client.post(f'/api/projects/{project_id}/challenges', headers=creator, json={
            'challenge': {
                'title': 'Explain the canonical project',
                'description': 'Read the project overview and submit a short evidence note that demonstrates genuine participation.',
                'category': 'LEARN',
                'verification_type': 'PROJECT_REVIEW',
                'config': {},
                'xp_reward': 40,
            },
            'reward_asset': 'P1CAN',
            'token_allocation': 200,
            'gross_reward_per_user': 100,
            'user_share_pct': 80,
            'nubagz_share_pct': 15,
            'referral_share_pct': 5,
            'max_users': 2,
            'reward_funding_reference': 'phase1-declared-funding',
        })
        assert created.status_code == 200, created.text
        challenge = created.json()
        challenge_id = challenge['id']
        legacy_campaign_id = challenge['legacy_campaign_id']
        assert challenge['project_id'] == project_id
        assert challenge['title'] == 'Explain the canonical project'
        assert challenge['funding_status'] == 'DECLARED'

        listed = client.get(f'/api/projects/{project_id}/challenges', headers=creator)
        assert listed.status_code == 200
        match = next(row for row in listed.json() if row['id'] == challenge_id)
        assert match['legacy_campaign_id'] == legacy_campaign_id
        assert match['title'] == challenge['title']

        verified = client.post(
            f'/api/funding/campaigns/{legacy_campaign_id}/verify',
            headers=admin,
            json={'amount': 200, 'tx_hash': 'phase1-verified-funding'},
        )
        assert verified.status_code == 200
        assert verified.json()['fully_funded'] is True
        assert verified.json()['campaign_status'] == 'LIVE'

        participant = register(client, 'phase1-domain-user@example.com', 'Phase1DomainUser')
        detail = client.get(f'/api/challenges/{challenge_id}', headers=participant)
        assert detail.status_code == 200, detail.text
        detail_body = detail.json()
        assert detail_body['title'] == challenge['title']
        assert detail_body['project_name'] == 'Phase One Canonical Project'
        assert detail_body['legacy_grouped'] is False
        assert detail_body['linked_requirement_count'] == 1
        assert detail_body['project_reward']['asset'] == 'P1CAN'
        assert detail_body['joined'] is False

        joined = client.post(f'/api/challenges/{challenge_id}/join', headers=participant)
        assert joined.status_code == 200, joined.text
        assert joined.json()['joined'] is True

        after_join = client.get(f'/api/challenges/{challenge_id}', headers=participant)
        assert after_join.status_code == 200
        assert after_join.json()['joined'] is True
