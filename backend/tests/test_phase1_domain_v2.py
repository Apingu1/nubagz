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


def create_project(client, creator, name, symbol):
    response = client.post('/api/projects', headers=creator, json={
        'name': name,
        'symbol': symbol,
        'description': 'A project created specifically to validate the NuBagz V2 Project to Challenge domain and final Phase 1 flow.',
        'website': 'https://example.com/phase-one',
        'chain': 'Avalanche',
    })
    assert response.status_code == 200, response.text
    return response.json()['id']


def create_review_challenge(client, creator, project_id, symbol, title):
    response = client.post(f'/api/projects/{project_id}/challenges', headers=creator, json={
        'challenge': {
            'title': title,
            'description': 'Read the project overview and submit a short evidence note that demonstrates genuine participation.',
            'category': 'LEARN',
            'verification_type': 'PROJECT_REVIEW',
            'config': {},
            'xp_reward': 50,
        },
        'reward_asset': symbol,
        'token_allocation': 200,
        'gross_reward_per_user': 100,
        'user_share_pct': 80,
        'nubagz_share_pct': 15,
        'referral_share_pct': 5,
        'max_users': 2,
        'reward_funding_reference': f'{symbol.lower()}-declared-funding',
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_phase1_complete_project_challenge_reward_flow_uses_canonical_surfaces():
    with TestClient(app) as client:
        creator = login(client, 'creator@demo.nubagz.com', 'Creator123!')
        admin = login(client, 'admin@demo.nubagz.com', 'Admin123!')
        project_id = create_project(client, creator, 'Phase One Complete Flow', 'P1END')
        challenge = create_review_challenge(client, creator, project_id, 'P1END', 'Verify the Phase One flow')
        challenge_id = challenge['id']

        assert challenge['project_id'] == project_id
        assert challenge['funding_status'] == 'DECLARED'
        assert challenge['compatibility_grouped'] is False
        assert 'legacy_campaign_id' not in challenge

        listed = client.get(f'/api/projects/{project_id}/challenges', headers=creator)
        assert listed.status_code == 200
        assert any(row['id'] == challenge_id and row['title'] == challenge['title'] for row in listed.json())

        funding = client.get(f'/api/challenges/{challenge_id}/funding', headers=creator)
        assert funding.status_code == 200
        assert funding.json()['status'] == 'DECLARED'
        assert funding.json()['challenge_id'] == challenge_id

        verified = client.post(
            f'/api/challenges/{challenge_id}/funding/verify',
            headers=admin,
            json={'amount': 200, 'tx_hash': 'phase1-complete-verified-funding'},
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()['fully_funded'] is True
        assert verified.json()['challenge_status'] == 'LIVE'

        participant = register(client, 'phase1-complete-user@example.com', 'Phase1CompleteUser')
        feed = client.get('/api/challenges', headers=participant)
        assert feed.status_code == 200
        assert any(row['id'] == challenge_id for row in feed.json())

        detail = client.get(f'/api/challenges/{challenge_id}', headers=participant)
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body['title'] == challenge['title']
        assert body['project_name'] == 'Phase One Complete Flow'
        assert body['compatibility_grouped'] is False
        assert body['linked_requirement_count'] == 1
        assert body['project_reward']['asset'] == 'P1END'
        assert body['joined'] is False
        assert body['compatibility_group_path'] is None
        assert 'legacy_campaign_id' not in body

        watch_status = client.get(f'/api/challenges/{challenge_id}/watch', headers=participant)
        assert watch_status.status_code == 200
        watched = client.post(f'/api/challenges/{challenge_id}/watch', headers=participant)
        assert watched.status_code == 200 and watched.json()['watched'] is True

        joined = client.post(f'/api/challenges/{challenge_id}/join', headers=participant)
        assert joined.status_code == 200, joined.text
        assert joined.json()['joined'] is True

        submitted = client.post(
            f'/api/challenges/{challenge_id}/complete',
            headers=participant,
            json={'answer': None, 'evidence': 'https://example.com/proof/phase-one'},
        )
        assert submitted.status_code == 200
        assert submitted.json()['status'] == 'PENDING'
        assert submitted.json()['reward_status'] is None

        queue = client.get('/api/challenges/submissions/project', headers=creator)
        assert queue.status_code == 200
        submission = next(row for row in queue.json() if row['challenge_id'] == challenge_id)
        decision = client.post(
            f"/api/challenges/completions/{submission['id']}/decision",
            headers=creator,
            json={'status': 'APPROVED'},
        )
        assert decision.status_code == 200
        assert decision.json()['completed'] is True
        assert decision.json()['reward_status'] == 'PENDING_SETTLEMENT'

        after = client.get(f'/api/challenges/{challenge_id}', headers=participant)
        assert after.status_code == 200
        assert after.json()['joined'] is True
        assert after.json()['enrollment_status'] == 'COMPLETED'
        assert after.json()['completion_status'] == 'APPROVED'

        earnings = client.get('/api/earnings/summary', headers=participant)
        assert earnings.status_code == 200
        payload = earnings.json()
        lifetime = {row['asset']: float(row['amount']) for row in payload['lifetime']}
        available = {row['asset']: float(row['amount']) for row in payload['available']}
        pending_settlement = {row['asset']: float(row['amount']) for row in payload['pending_settlement']}
        assert lifetime['P1END'] == 80.0
        assert available.get('P1END', 0) == 0
        assert pending_settlement['P1END'] == 80.0

        withdrawal = client.post('/api/users/withdrawals', headers=participant, json={
            'asset_symbol': 'P1END',
            'amount': 1,
            'chain': 'Avalanche',
            'wallet_address': '0x1111111111111111111111111111111111111111',
        })
        # Pending settlement is not withdrawable; a saved reward destination is
        # deliberately irrelevant to the available-balance gate here.
        assert withdrawal.status_code == 400

        activity = client.get('/api/activity', headers=participant)
        assert activity.status_code == 200
        event = next(row for row in activity.json()['events'] if row['username'] == 'Phase1CompleteUser')
        assert event['link_path'] == f'/app/challenges/{challenge_id}'

        paused = client.post(f'/api/challenges/{challenge_id}/pause', headers=creator)
        assert paused.status_code == 200 and paused.json()['status'] == 'PAUSED'
        assert client.get(f'/api/challenges/{challenge_id}', headers=participant).status_code == 404
        resumed = client.post(f'/api/challenges/{challenge_id}/resume', headers=creator)
        assert resumed.status_code == 200 and resumed.json()['status'] == 'LIVE'

        removed = client.delete(f'/api/challenges/{challenge_id}/watch', headers=participant)
        assert removed.status_code == 200 and removed.json()['watched'] is False


def test_phase1_reports_target_challenge_without_exposing_campaign_to_users():
    with TestClient(app) as client:
        creator = login(client, 'creator@demo.nubagz.com', 'Creator123!')
        admin = login(client, 'admin@demo.nubagz.com', 'Admin123!')
        project_id = create_project(client, creator, 'Phase One Report Target', 'P1RPT')
        challenge = create_review_challenge(client, creator, project_id, 'P1RPT', 'Reportable canonical Challenge')
        challenge_id = challenge['id']

        assert client.post(
            f'/api/challenges/{challenge_id}/funding/verify',
            headers=admin,
            json={'amount': 200, 'tx_hash': 'phase1-report-verified'},
        ).status_code == 200

        reporter = register(client, 'phase1-report-user@example.com', 'Phase1ReportUser')
        report = client.post('/api/reports', headers=reporter, json={
            'target_type': 'CHALLENGE',
            'target_id': challenge_id,
            'category': 'SAFETY',
            'detail': 'This is a Phase 1 test report proving that users can report a canonical Challenge directly.',
        })
        assert report.status_code == 200, report.text
        case = report.json()
        assert case['target_type'] == 'CHALLENGE'
        assert case['target_id'] == challenge_id

        affected = client.get('/api/reports/affected', headers=creator)
        assert affected.status_code == 200
        assert any(row['id'] == case['id'] for row in affected.json())

        resolved = client.post(f"/api/reports/{case['id']}/resolve", headers=admin, json={
            'status': 'RESOLVED',
            'action': 'SUSPEND_CHALLENGE',
            'note': 'Challenge suspended by the Phase 1 moderation compatibility test.',
        })
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()['resolution_action'] == 'SUSPEND_CHALLENGE'
        assert client.get(f'/api/challenges/{challenge_id}', headers=reporter).status_code == 404
