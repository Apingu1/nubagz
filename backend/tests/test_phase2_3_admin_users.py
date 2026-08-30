from decimal import Decimal

from fastapi.testclient import TestClient

from app.admin_user_models import AdminUserAction, UserRewardHold
from app.db import SessionLocal
from app.main import app
from app.models import LedgerEntry, User
from app.risk_models import FraudSignal, UserTrustProfile


def login(client, email, password):
    response = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200
    return {'Authorization': f"Bearer {response.json()['access_token']}"}


def register(client, email, username):
    response = client.post('/api/auth/register', json={
        'email': email,
        'username': username,
        'password': 'Phase23Pass123!',
    })
    assert response.status_code == 200
    return response.json()['user']['id'], {'Authorization': f"Bearer {response.json()['access_token']}"}


def test_phase2_3_admin_users_search_trust_reward_hold_state_and_session_controls():
    with TestClient(app) as client:
        admin = login(client, 'admin@demo.nubagz.com', 'Admin123!')
        user_id, user_headers = register(client, 'phase23-user@example.com', 'Phase23User')

        payout = '0x2323232323232323232323232323232323232323'
        saved = client.post('/api/users/payout-addresses', headers=user_headers, json={
            'address': payout,
            'chain': 'Robinhood',
            'label': 'Phase 2.3 reward destination',
            'make_primary': True,
        })
        assert saved.status_code == 200

        db = SessionLocal()
        try:
            db.add(LedgerEntry(
                user_id=user_id,
                asset_symbol='P23',
                amount=Decimal('25'),
                entry_type='TEST_SETTLED_REWARD',
                status='AVAILABLE',
                note='Phase 2.3 withdrawal-hold regression balance',
            ))
            db.add(FraudSignal(
                user_id=user_id,
                signal_type='PHASE23_REVIEW_SIGNAL',
                severity='MEDIUM',
                detail='Test-only signal for Admin investigation controls.',
            ))
            db.commit()
            signal_id = db.query(FraudSignal).filter(
                FraudSignal.user_id == user_id,
                FraudSignal.signal_type == 'PHASE23_REVIEW_SIGNAL',
            ).first().id
        finally:
            db.close()

        # Admin Users is protected independently from normal authenticated users.
        denied = client.get('/api/admin/users', headers=user_headers)
        assert denied.status_code == 403

        # Search spans account identity and saved reward destinations.
        by_email = client.get('/api/admin/users?q=phase23-user@example.com', headers=admin)
        assert by_email.status_code == 200
        assert by_email.json()['total'] >= 1
        assert any(row['id'] == user_id for row in by_email.json()['users'])
        by_wallet = client.get(f'/api/admin/users?q={payout[-12:]}', headers=admin)
        assert by_wallet.status_code == 200
        assert any(row['id'] == user_id for row in by_wallet.json()['users'])

        detail = client.get(f'/api/admin/users/{user_id}', headers=admin)
        assert detail.status_code == 200
        payload = detail.json()
        assert payload['account']['id'] == user_id
        assert payload['account']['account_state'] == 'ACTIVE'
        assert payload['account']['wallet']['reward_destination'].lower() == payout.lower()
        assert payload['trust']['signals'][0]['type'] == 'PHASE23_REVIEW_SIGNAL'
        assert 'password_hash' not in str(payload)

        # Sensitive actions require a meaningful audit reason.
        short_hold = client.post(f'/api/admin/users/{user_id}/rewards/hold', headers=admin, json={'reason': 'short'})
        assert short_hold.status_code == 422

        held = client.post(f'/api/admin/users/{user_id}/rewards/hold', headers=admin, json={
            'reason': 'Hold payouts while the test risk signal is investigated.',
        })
        assert held.status_code == 200 and held.json()['reward_hold'] is True

        blocked_withdrawal = client.post('/api/users/withdrawals', headers=user_headers, json={
            'asset_symbol': 'P23',
            'amount': 5,
            'chain': 'Robinhood',
            'wallet_address': payout,
        })
        assert blocked_withdrawal.status_code == 403
        assert 'held' in blocked_withdrawal.json()['detail'].lower()

        released = client.post(f'/api/admin/users/{user_id}/rewards/release', headers=admin, json={
            'reason': 'Investigation complete; release the test payout hold.',
        })
        assert released.status_code == 200 and released.json()['reward_hold'] is False

        allowed_withdrawal = client.post('/api/users/withdrawals', headers=user_headers, json={
            'asset_symbol': 'P23',
            'amount': 5,
            'chain': 'Robinhood',
            'wallet_address': payout,
        })
        assert allowed_withdrawal.status_code == 200

        short_trust = client.post(f'/api/admin/users/{user_id}/trust/correct', headers=admin, json={
            'trust_level': 'REVIEW',
            'reason': 'tiny',
        })
        assert short_trust.status_code == 422

        trust = client.post(f'/api/admin/users/{user_id}/trust/correct', headers=admin, json={
            'trust_level': 'REVIEW',
            'reason': 'Manual review is appropriate while the recorded signal is assessed.',
        })
        assert trust.status_code == 200
        assert trust.json()['trust_level'] == 'REVIEW'
        # Trust and account state are separate concepts.
        assert trust.json()['account_state'] == 'ACTIVE'

        signal = client.post(f'/api/admin/users/{user_id}/signals/{signal_id}', headers=admin, json={
            'status': 'RESOLVED',
            'reason': 'Reviewed the test evidence and closed this individual signal.',
        })
        assert signal.status_code == 200 and signal.json()['status'] == 'RESOLVED'

        restricted = client.patch(f'/api/admin/users/{user_id}/state', headers=admin, json={
            'account_state': 'RESTRICTED',
            'reason': 'Temporarily restrict new value actions while review is completed.',
        })
        assert restricted.status_code == 200
        assert restricted.json()['account_state'] == 'RESTRICTED'
        assert restricted.json()['sessions_revoked'] == 0
        assert client.get('/api/auth/me', headers=user_headers).status_code == 200

        suspended = client.patch(f'/api/admin/users/{user_id}/state', headers=admin, json={
            'account_state': 'SUSPENDED',
            'reason': 'Suspend the account and revoke all active sessions for investigation.',
        })
        assert suspended.status_code == 200
        assert suspended.json()['account_state'] == 'SUSPENDED'
        assert suspended.json()['sessions_revoked'] >= 1
        assert client.get('/api/auth/me', headers=user_headers).status_code == 401

        restored = client.patch(f'/api/admin/users/{user_id}/state', headers=admin, json={
            'account_state': 'ACTIVE',
            'reason': 'Identity review completed; restore normal account access.',
        })
        assert restored.status_code == 200 and restored.json()['account_state'] == 'ACTIVE'
        # Revoked sessions stay revoked after restoration; a fresh login is required.
        assert client.get('/api/auth/me', headers=user_headers).status_code == 401
        fresh_user_headers = login(client, 'phase23-user@example.com', 'Phase23Pass123!')
        assert client.get('/api/auth/me', headers=fresh_user_headers).status_code == 200

        revoked = client.post(f'/api/admin/users/{user_id}/sessions/revoke', headers=admin, json={
            'reason': 'Explicitly revoke the fresh session to test the Admin security control.',
        })
        assert revoked.status_code == 200 and revoked.json()['sessions_revoked'] >= 1
        assert client.get('/api/auth/me', headers=fresh_user_headers).status_code == 401

        db = SessionLocal()
        try:
            account = db.get(User, user_id)
            assert account.account_state == 'ACTIVE' and account.is_active is True
            # Moderation preserves reward/history records rather than deleting them.
            assert db.query(LedgerEntry).filter(LedgerEntry.user_id == user_id).count() >= 1
            profile = db.query(UserTrustProfile).filter(UserTrustProfile.user_id == user_id).first()
            assert profile is not None and profile.trust_level == 'REVIEW'
            holds = db.query(UserRewardHold).filter(UserRewardHold.user_id == user_id).all()
            assert len(holds) == 1 and holds[0].status == 'RELEASED'
            action_types = {
                row.action_type for row in db.query(AdminUserAction).filter(AdminUserAction.target_user_id == user_id).all()
            }
            assert {'REWARDS_HELD', 'REWARDS_RELEASED', 'TRUST_CORRECTED', 'RISK_SIGNAL_UPDATED', 'ACCOUNT_STATE_CHANGED', 'SESSIONS_REVOKED'} <= action_types
        finally:
            db.close()

        final_detail = client.get(f'/api/admin/users/{user_id}', headers=admin)
        assert final_detail.status_code == 200
        final = final_detail.json()
        assert final['account']['account_state'] == 'ACTIVE'
        assert final['account']['reward_hold']['active'] is False
        assert any(row['action_type'] == 'SESSIONS_REVOKED' for row in final['admin_actions'])


def test_phase2_3_legacy_trust_admin_path_requires_reason_and_is_audited():
    with TestClient(app) as client:
        admin = login(client, 'admin@demo.nubagz.com', 'Admin123!')
        user_id, _ = register(client, 'phase23-legacy@example.com', 'Phase23Legacy')

        missing_reason = client.post(f'/api/risk/users/{user_id}/trust', headers=admin, json={
            'trust_level': 'VERIFIED',
            'note': '',
        })
        assert missing_reason.status_code == 422

        corrected = client.post(f'/api/risk/users/{user_id}/trust', headers=admin, json={
            'trust_level': 'VERIFIED',
            'note': 'Compatibility route review completed with verified identity evidence.',
        })
        assert corrected.status_code == 200 and corrected.json()['trust_level'] == 'VERIFIED'

        db = SessionLocal()
        try:
            action = db.query(AdminUserAction).filter(
                AdminUserAction.target_user_id == user_id,
                AdminUserAction.action_type == 'TRUST_CORRECTED_COMPAT',
            ).first()
            assert action is not None
            assert 'verified identity evidence' in action.reason
        finally:
            db.close()
