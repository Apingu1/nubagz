from alembic import command
from alembic.config import Config
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

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


def test_restricted_account_keeps_read_access_but_cannot_start_reward_or_swap_actions():
    with TestClient(app) as client:
        signup = client.post('/api/auth/register', json={
            'email': 'phase2-1-restricted@example.com',
            'username': 'Phase21Restricted',
            'password': 'Phase21Security123!',
        })
        assert signup.status_code == 200, signup.text
        user_id = signup.json()['user']['id']
        headers = {'Authorization': f"Bearer {signup.json()['access_token']}"}

        with SessionLocal() as db:
            user = db.get(User, user_id)
            user.account_state = 'RESTRICTED'
            db.commit()

        # Restricted users retain access to their own account/history surfaces.
        me = client.get('/api/auth/me', headers=headers)
        assert me.status_code == 200
        assert me.json()['account_state'] == 'RESTRICTED'
        assert client.get('/api/earnings/summary', headers=headers).status_code == 200

        # Capability gates run before route-specific resource/wallet validation.
        join = client.post('/api/challenges/999999/join', headers=headers)
        assert join.status_code == 403
        assert 'restricted' in join.json()['detail'].lower()
        complete = client.post('/api/challenges/999999/complete', headers=headers, json={})
        assert complete.status_code == 403
        assert 'restricted' in complete.json()['detail'].lower()
        swap = client.post('/api/swaps/quote', headers=headers, json={
            'chain': 'Robinhood',
            'sell_token': 'native',
            'buy_token': '0x1111111111111111111111111111111111111111',
            'sell_amount': '1',
            'slippage_bps': 100,
        })
        assert swap.status_code == 403
        assert 'restricted' in swap.json()['detail'].lower()

        with SessionLocal() as db:
            user = db.get(User, user_id)
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


def test_phase1_shaped_database_upgrades_without_losing_user_wallet_or_reward_rows(tmp_path):
    db_path = tmp_path / 'phase1-shaped.db'
    url = f'sqlite:///{db_path}'
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                email VARCHAR(255) NOT NULL,
                username VARCHAR(64) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(24) NOT NULL,
                xp INTEGER NOT NULL,
                bag_score INTEGER NOT NULL,
                streak_days INTEGER NOT NULL,
                referral_code VARCHAR(32) NOT NULL,
                referred_by_id INTEGER,
                wallet_address VARCHAR(255),
                wallet_chain VARCHAR(32),
                is_active BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL,
                last_active_at DATETIME NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE wallet_connections (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                address VARCHAR(255) NOT NULL,
                chain_type VARCHAR(24) NOT NULL,
                chain_id INTEGER,
                wallet_client_type VARCHAR(64) NOT NULL,
                connector_type VARCHAR(64) NOT NULL,
                wallet_type VARCHAR(24) NOT NULL,
                is_primary BOOLEAN NOT NULL,
                verified_at DATETIME,
                last_connected_at DATETIME NOT NULL,
                created_at DATETIME NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE ledger_entries (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                campaign_id INTEGER,
                asset_symbol VARCHAR(24) NOT NULL,
                amount NUMERIC(36,8) NOT NULL,
                entry_type VARCHAR(32) NOT NULL,
                status VARCHAR(24) NOT NULL,
                note VARCHAR(255),
                created_at DATETIME NOT NULL
            )
        """))
        connection.execute(text("""
            INSERT INTO users VALUES (
                91,'preserved@example.com','PreservedUser','hash','USER',10,120,2,'KEEP91',NULL,
                '0x1111111111111111111111111111111111111111','Avalanche',1,
                '2026-08-01 00:00:00','2026-08-29 00:00:00'
            )
        """))
        connection.execute(text("""
            INSERT INTO wallet_connections VALUES (
                81,91,'0x2222222222222222222222222222222222222222','ethereum',43114,
                'metamask','injected','EXTERNAL',0,'2026-08-20 00:00:00','2026-08-29 00:00:00','2026-08-20 00:00:00'
            )
        """))
        connection.execute(text("""
            INSERT INTO ledger_entries VALUES (
                71,91,NULL,'KEEP',80,'CAMPAIGN_REWARD','AVAILABLE','Phase 1 approved compatibility reward','2026-08-29 00:00:00'
            )
        """))

    original_url = settings.database_url
    settings.database_url = url
    try:
        config = Config('alembic.ini')
        command.upgrade(config, 'head')
    finally:
        settings.database_url = original_url

    migrated = create_engine(url)
    with migrated.connect() as connection:
        user = connection.execute(text("SELECT email, username, account_state FROM users WHERE id=91")).one()
        wallet = connection.execute(text("SELECT address, is_primary_interactive FROM wallet_connections WHERE id=81")).one()
        reward = connection.execute(text("SELECT amount, status FROM ledger_entries WHERE id=71")).one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        sessions = connection.execute(text("SELECT COUNT(*) FROM user_sessions")).scalar_one()

    assert user.email == 'preserved@example.com'
    assert user.username == 'PreservedUser'
    assert user.account_state == 'ACTIVE'
    assert wallet.address == '0x2222222222222222222222222222222222222222'
    assert bool(wallet.is_primary_interactive) is True
    assert float(reward.amount) == 80.0
    assert reward.status == 'PENDING_SETTLEMENT'
    assert revision == '20260829_0002'
    assert sessions == 0
