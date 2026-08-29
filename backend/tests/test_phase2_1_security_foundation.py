import pytest
from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.db import SessionLocal
from app.main import app
from app.models import User, UserSession
from app.security import decode_access_token


def test_access_tokens_are_session_bound_and_logout_revokes_server_session():
    with TestClient(app) as client:
        login = client.post('/api/auth/login', json={
            'email': 'demo@demo.nubagz.com',
            'password': 'Demo123!',
        })
        assert login.status_code == 200, login.text
        token = login.json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}

        claims = decode_access_token(token)
        assert claims['aud'] == settings.jwt_audience
        assert claims['iss'] == 'nubagz'
        assert claims['sid']
        assert claims['jti']
        assert client.get('/api/auth/me', headers=headers).status_code == 200

        with SessionLocal() as db:
            session = db.query(UserSession).filter(UserSession.session_id == claims['sid']).first()
            assert session is not None
            assert session.revoked_at is None

        logout = client.post('/api/auth/logout', headers=headers)
        assert logout.status_code == 204
        assert client.get('/api/auth/me', headers=headers).status_code == 401

        with SessionLocal() as db:
            session = db.query(UserSession).filter(UserSession.session_id == claims['sid']).first()
            assert session is not None
            assert session.revoked_at is not None
            assert session.revoke_reason == 'USER_LOGOUT'


def test_suspended_account_invalidates_an_already_issued_session_without_deleting_history():
    with TestClient(app) as client:
        signup = client.post('/api/auth/register', json={
            'email': 'phase2-1-suspended@example.com',
            'username': 'Phase21Suspended',
            'password': 'Phase21Security123!',
        })
        assert signup.status_code == 200, signup.text
        user_id = signup.json()['user']['id']
        headers = {'Authorization': f"Bearer {signup.json()['access_token']}"}
        assert signup.json()['user']['account_state'] == 'ACTIVE'
        assert client.get('/api/auth/me', headers=headers).status_code == 200

        with SessionLocal() as db:
            user = db.get(User, user_id)
            user.account_state = 'SUSPENDED'
            db.commit()

        assert client.get('/api/auth/me', headers=headers).status_code == 401

        with SessionLocal() as db:
            user = db.get(User, user_id)
            assert user is not None
            assert user.email == 'phase2-1-suspended@example.com'
            assert user.account_state == 'SUSPENDED'
            # Restore only to avoid contaminating unrelated tests; the assertion
            # above proves suspension does not delete the account or its history.
            user.account_state = 'ACTIVE'
            db.commit()


def test_production_security_rejects_hs256_or_missing_rsa_keys():
    insecure = Settings(
        environment='production',
        jwt_algorithm='HS256',
        jwt_secret='test-only-secret',
        jwt_private_key=None,
        jwt_public_key=None,
    )
    with pytest.raises(RuntimeError, match='RS256'):
        insecure.validate_runtime_security()

    missing_keys = Settings(
        environment='production',
        jwt_algorithm='RS256',
        jwt_private_key='',
        jwt_public_key='',
    )
    with pytest.raises(RuntimeError, match='JWT_PRIVATE_KEY'):
        missing_keys.validate_runtime_security()
