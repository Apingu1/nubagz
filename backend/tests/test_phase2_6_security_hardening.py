from fastapi.testclient import TestClient

from app.abuse_models import NetworkObservation
from app.config import Settings, settings
from app.db import SessionLocal
from app.main import app
from app.models import PayoutAddress, User
from app.rate_limit import limiter
from app.risk_models import FraudSignal


def register(client: TestClient, email: str, username: str):
    response = client.post('/api/auth/register', json={
        'email': email,
        'username': username,
        'password': 'Phase26Security123!',
    })
    assert response.status_code == 200, response.text
    return response.json()['user']['id'], {'Authorization': f"Bearer {response.json()['access_token']}"}


def test_phase2_6_auth_throttle_returns_retry_after_without_captcha_bypass():
    old_minute = settings.rate_limit_auth_per_minute
    old_15m = settings.rate_limit_auth_per_15_minutes
    old_secret = settings.turnstile_secret_key
    old_site = settings.turnstile_site_key
    settings.rate_limit_auth_per_minute = 2
    settings.rate_limit_auth_per_15_minutes = 10
    settings.turnstile_secret_key = ''
    settings.turnstile_site_key = ''
    limiter.clear()
    try:
        with TestClient(app) as client:
            payload = {'email': 'not-a-user@example.com', 'password': 'wrong-password'}
            assert client.post('/api/auth/login', json=payload).status_code == 401
            assert client.post('/api/auth/login', json=payload).status_code == 401
            blocked = client.post('/api/auth/login', json=payload)
            assert blocked.status_code == 429
            assert blocked.headers.get('Retry-After')
            body = blocked.json()
            assert body['code'] == 'RATE_LIMITED'
            assert body['retry_after'] >= 1
            assert body['human_verification_required'] is False
    finally:
        settings.rate_limit_auth_per_minute = old_minute
        settings.rate_limit_auth_per_15_minutes = old_15m
        settings.turnstile_secret_key = old_secret
        settings.turnstile_site_key = old_site
        limiter.clear()


def test_production_security_requires_stable_abuse_signal_key():
    missing_abuse_key = Settings(
        environment='production',
        jwt_algorithm='RS256',
        jwt_private_key='test-private-key-present',
        jwt_public_key='test-public-key-present',
        admin_security_key='test-admin-key-present',
        abuse_signal_key='',
    )
    try:
        missing_abuse_key.validate_runtime_security()
        raise AssertionError('Production security should reject a missing ABUSE_SIGNAL_KEY')
    except RuntimeError as exc:
        assert 'ABUSE_SIGNAL_KEY' in str(exc)


def test_network_and_device_signals_are_keyed_and_combined_without_changing_account_state():
    with TestClient(app) as client:
        first_id, first = register(client, 'phase26-one@example.com', 'Phase26One')
        second_id, second = register(client, 'phase26-two@example.com', 'Phase26Two')

        shared_install = 'phase26-shared-local-install-id-0001'
        assert client.post('/api/risk/context', headers=first, json={'install_id': shared_install}).status_code == 200
        assert client.post('/api/risk/context', headers=second, json={'install_id': shared_install}).status_code == 200

        # Reward-destination reuse is a stronger independent signal family. It is
        # intentionally combined with environment evidence rather than treating a
        # shared network/browser context as conclusive on its own.
        shared_reward = '0x1111111111111111111111111111111111111111'
        with SessionLocal() as db:
            db.add(PayoutAddress(user_id=first_id, address=shared_reward, chain='Avalanche', label='Shared test destination', is_primary=True))
            db.add(PayoutAddress(user_id=second_id, address=shared_reward, chain='Avalanche', label='Shared test destination', is_primary=True))
            db.commit()

        risk = client.get('/api/risk/me', headers=first)
        assert risk.status_code == 200, risk.text
        signal_types = {row['type'] for row in risk.json()['signals']}
        assert 'SHARED_PAYOUT_ADDRESS' in signal_types
        assert 'SHARED_DEVICE_INSTALL' in signal_types
        assert 'SHARED_NETWORK_SIGNAL' in signal_types
        assert 'COMBINED_SYBIL_PATTERN' in signal_types

        with SessionLocal() as db:
            account = db.get(User, first_id)
            assert account.account_state == 'ACTIVE'
            network = db.query(NetworkObservation).filter(NetworkObservation.user_id == first_id).first()
            assert network is not None
            assert len(network.ip_hash) == 64
            assert network.ip_hash not in {'testclient', '127.0.0.1', '::1'}
            assert 'testclient' not in network.ip_hash
            open_signals = {row.signal_type for row in db.query(FraudSignal).filter(FraudSignal.user_id == first_id, FraudSignal.status == 'OPEN').all()}
            assert 'COMBINED_SYBIL_PATTERN' in open_signals

        assert 'raw IP' in risk.json()['privacy_note']
        assert 'automatic ban' in risk.json()['privacy_note']
