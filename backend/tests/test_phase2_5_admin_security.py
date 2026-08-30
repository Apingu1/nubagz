import time

from fastapi.testclient import TestClient

from app.admin_security import totp_code
from app.admin_security_models import AdminAuditEvent, AdminMfaCredential
from app.db import SessionLocal
from app.main import app


def login(client, email='admin@demo.nubagz.com', password='Admin123!'):
    response = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200, response.text
    return {'Authorization': f"Bearer {response.json()['access_token']}"}


def register(client):
    response = client.post('/api/auth/register', json={
        'email': 'phase25-target@example.com',
        'username': 'Phase25Target',
        'password': 'Phase25Pass123!',
    })
    assert response.status_code == 200, response.text
    return response.json()['user']['id']


def test_phase2_5_admin_mfa_privilege_binding_and_audit():
    with TestClient(app) as client:
        admin = login(client)
        target_id = register(client)

        # Read-only Admin investigation remains available without privileged mode.
        assert client.get('/api/admin/users', headers=admin).status_code == 200

        blocked = client.patch(f'/api/admin/users/{target_id}/state', headers=admin, json={
            'account_state': 'UNDER_REVIEW',
            'reason': 'Phase 2.5 verifies that sensitive writes fail closed before MFA.',
        })
        assert blocked.status_code == 428
        assert 'mfa' in blocked.json()['detail'].lower()

        wrong_setup = client.post('/api/admin/security/mfa/setup', headers=admin, json={'password': 'wrong-password'})
        assert wrong_setup.status_code == 401

        setup = client.post('/api/admin/security/mfa/setup', headers=admin, json={'password': 'Admin123!'})
        assert setup.status_code == 200, setup.text
        secret = setup.json()['secret']
        assert secret and secret not in str(client.get('/api/admin/security/status', headers=admin).json())

        counter = int(time.time() // 30)
        confirm_code = totp_code(secret, counter)
        confirmed = client.post('/api/admin/security/mfa/confirm', headers=admin, json={'code': confirm_code})
        assert confirmed.status_code == 200, confirmed.text

        # A TOTP code is single-use: confirmation cannot be replayed to unlock.
        replay = client.post('/api/admin/security/privilege/start', headers=admin, json={
            'password': 'Admin123!',
            'code': confirm_code,
        })
        assert replay.status_code == 401

        unlock_code = totp_code(secret, counter + 1)
        unlocked = client.post('/api/admin/security/privilege/start', headers=admin, json={
            'password': 'Admin123!',
            'code': unlock_code,
        })
        assert unlocked.status_code == 200, unlocked.text
        privilege_token = unlocked.json()['privilege_token']
        privileged = {**admin, 'X-NuBagz-Admin-Privilege': privilege_token}

        changed = client.patch(f'/api/admin/users/{target_id}/state', headers=privileged, json={
            'account_state': 'UNDER_REVIEW',
            'reason': 'Privileged Phase 2.5 moderation after password reauthentication and TOTP.',
        })
        assert changed.status_code == 200, changed.text
        assert changed.json()['account_state'] == 'UNDER_REVIEW'

        audit = client.get('/api/admin/security/audit?limit=100', headers=privileged)
        assert audit.status_code == 200, audit.text
        types = {row['event_type'] for row in audit.json()['events']}
        assert {'MFA_SETUP_STARTED', 'MFA_ENABLED', 'PRIVILEGE_SESSION_STARTED', 'ADMIN_ROUTE_ACCESS'} <= types

        # Privilege is bound to the exact ordinary session and cannot be copied
        # into a second login session for the same Admin user.
        second_admin = login(client)
        copied = {**second_admin, 'X-NuBagz-Admin-Privilege': privilege_token}
        denied_cross_session = client.patch(f'/api/admin/users/{target_id}/state', headers=copied, json={
            'account_state': 'ACTIVE',
            'reason': 'This copied privilege token must not work from a second ordinary session.',
        })
        assert denied_cross_session.status_code == 428

        locked = client.post('/api/admin/security/privilege/revoke', headers=privileged)
        assert locked.status_code == 200
        denied_after_lock = client.patch(f'/api/admin/users/{target_id}/state', headers=privileged, json={
            'account_state': 'ACTIVE',
            'reason': 'A revoked privileged session must not authorize any further Admin write.',
        })
        assert denied_after_lock.status_code == 428

        with SessionLocal() as db:
            credential = db.query(AdminMfaCredential).first()
            assert credential is not None and credential.enabled is True
            assert secret not in credential.secret_ciphertext
            assert db.query(AdminAuditEvent).count() >= 5
