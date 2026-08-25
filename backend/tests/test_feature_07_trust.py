from fastapi.testclient import TestClient
from app.main import app


def login(client, email, password):
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200
    return {'Authorization': f"Bearer {r.json()['access_token']}"}


def test_project_trust_requires_admin_verified_evidence_before_score_increases():
    with TestClient(app) as client:
        creator = login(client, 'creator@demo.nubagz.com', 'Creator123!')
        admin = login(client, 'admin@demo.nubagz.com', 'Admin123!')
        project = next(p for p in client.get('/api/projects/mine', headers=creator).json() if p['status'] in {'LIVE','APPROVED'})
        project_id = project['id']

        profile = client.patch(f'/api/projects/{project_id}/profile', headers=creator, json={
            'website': 'https://trust-profile.example.com',
            'treasury_address': '0x2222222222222222222222222222222222222222',
        })
        assert profile.status_code == 200
        assert profile.json()['website'] == 'https://trust-profile.example.com'

        submission = client.post('/api/trust/evidence', headers=creator, json={
            'project_id': project_id,
            'contract_address': '0x1111111111111111111111111111111111111111',
            'token_launch_date': '2025-01-01',
            'docs_url': 'https://docs.example.com',
            'socials_url': 'https://social.example.com',
            'team_url': 'https://example.com/team',
            'contract_source_verified': True,
            'dangerous_permissions_absent': True,
            'liquidity_verified': True,
            'holder_distribution_verified': True,
            'team_verified': True,
            'docs_verified': True,
            'socials_verified': True,
        })
        assert submission.status_code == 200

        before = client.get(f'/api/trust/projects/{project_id}').json()
        assert before['score_version'] == '3.0'
        assert before['evidence']['status'] == 'SUBMITTED'
        assert before['evidence']['team_url'] == 'https://example.com/team'
        assert before['project_profile']['website'] == 'https://trust-profile.example.com'
        assert before['project_profile']['treasury_address'] == '0x2222222222222222222222222222222222222222'
        assert 'approval' not in before['factors']
        assert before['factors']['contract_safety'] == 0
        assert before['factors']['market_structure'] == 0
        assert before['factors']['identity_community'] == 0

        queue = client.get('/api/trust/admin/evidence', headers=admin)
        assert queue.status_code == 200
        assert any(row['project_id'] == project_id and row['evidence']['status'] == 'SUBMITTED' for row in queue.json())

        verified = client.post(f'/api/trust/admin/evidence/{project_id}/verify', headers=admin, json={'status': 'VERIFIED', 'notes': 'Evidence checked for feature test.'})
        assert verified.status_code == 200
        after = client.get(f'/api/trust/projects/{project_id}').json()
        assert after['evidence']['status'] == 'VERIFIED'
        assert after['factors']['contract_safety'] == 15
        assert after['factors']['market_structure'] == 10
        assert after['factors']['identity_community'] == 10
        assert after['score'] > before['score']
        assert after['score'] == min(100, sum(after['factors'].values()))
        assert 'not an endorsement' in after['disclaimer'].lower()

        rows = client.get('/api/trust/projects')
        assert rows.status_code == 200
        public = next(row for row in rows.json() if row['project_id'] == project_id)
        assert public['score'] == after['score']
        assert public['evidence']['status'] == 'VERIFIED'
