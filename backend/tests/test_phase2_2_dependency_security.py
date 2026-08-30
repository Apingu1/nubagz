from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.challenge_dependencies import requirement_codes
from app.challenge_models import Challenge, SocialAccount
from app.db import SessionLocal
from app.main import app
from app.models import PayoutAddress, User, WalletConnection
from app.social_auth import sync_social_accounts


def login(client, email, password):
    response = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200, response.text
    return {'Authorization': f"Bearer {response.json()['access_token']}"}


def register(client, email, username):
    response = client.post('/api/auth/register', json={
        'email': email,
        'username': username,
        'password': 'Phase22Security123!',
    })
    assert response.status_code == 200, response.text
    return response.json()['user']['id'], {'Authorization': f"Bearer {response.json()['access_token']}"}


def create_project(client, creator, name, symbol):
    response = client.post('/api/projects', headers=creator, json={
        'name': name,
        'symbol': symbol,
        'description': 'A Phase 2.2 project used to validate deterministic Challenge identity and wallet dependency gates.',
        'website': 'https://example.com/phase22',
        'chain': 'Avalanche',
    })
    assert response.status_code == 200, response.text
    return response.json()['id']


def create_challenge(client, creator, project_id, symbol, challenge):
    response = client.post(f'/api/projects/{project_id}/challenges', headers=creator, json={
        'challenge': challenge,
        'reward_asset': symbol,
        'token_allocation': 200,
        'gross_reward_per_user': 100,
        'user_share_pct': 80,
        'nubagz_share_pct': 15,
        'referral_share_pct': 5,
        'max_users': 2,
        'reward_funding_reference': f'phase22-{symbol.lower()}-declared',
    })
    assert response.status_code == 200, response.text
    return response.json()['id']


def verify_funding(client, admin, challenge_id):
    response = client.post(
        f'/api/challenges/{challenge_id}/funding/verify',
        headers=admin,
        json={'amount': 200, 'tx_hash': f'phase22-verified-{challenge_id}'},
    )
    assert response.status_code == 200, response.text


def requirement_map(payload):
    return {row['code']: row for row in payload['dependency_preflight']['requirements']}


def test_x_challenge_exposes_preflight_and_blocks_join_until_provider_identity_exists():
    with TestClient(app) as client:
        creator = login(client, 'creator@demo.nubagz.com', 'Creator123!')
        admin = login(client, 'admin@demo.nubagz.com', 'Admin123!')
        project_id = create_project(client, creator, 'Phase 22 X Dependency', 'P22X')
        challenge_id = create_challenge(client, creator, project_id, 'P22X', {
            'title': 'Post the Phase 2.2 proof on X',
            'description': 'Publish the configured public X proof so NuBagz can verify the provider-issued account identity.',
            'category': 'SOCIAL',
            'provider': 'X',
            'action': 'POST',
            'verification_type': 'AUTO',
            'config': {'required_text': 'NuBagz Phase 2.2'},
            'xp_reward': 50,
        })
        verify_funding(client, admin, challenge_id)

        user_id, participant = register(client, 'phase22-x-user@example.com', 'Phase22XUser')
        detail = client.get(f'/api/challenges/{challenge_id}', headers=participant)
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body['dependency_preflight']['server_ready'] is False
        reqs = requirement_map(body)
        assert reqs['SOCIAL_X']['satisfied'] is False
        assert reqs['SOCIAL_X']['action_path'] == '/app/bag'

        blocked = client.post(f'/api/challenges/{challenge_id}/join', headers=participant)
        assert blocked.status_code == 409
        assert 'connect x' in blocked.json()['detail'].lower()

        with SessionLocal() as db:
            db.add(SocialAccount(
                user_id=user_id,
                provider='X',
                provider_user_id='phase22-x-provider-user',
                privy_user_id='did:privy:phase22-x-user',
                username='phase22x',
                connected_at=datetime.now(UTC),
                last_verified_at=datetime.now(UTC),
            ))
            db.commit()

        ready = client.get(f'/api/challenges/{challenge_id}', headers=participant)
        assert ready.status_code == 200
        assert ready.json()['dependency_preflight']['server_ready'] is True
        assert requirement_map(ready.json())['SOCIAL_X']['satisfied'] is True
        joined = client.post(f'/api/challenges/{challenge_id}/join', headers=participant)
        assert joined.status_code == 200, joined.text


def test_payout_only_address_never_satisfies_onchain_interactive_wallet_dependency():
    with TestClient(app) as client:
        creator = login(client, 'creator@demo.nubagz.com', 'Creator123!')
        admin = login(client, 'admin@demo.nubagz.com', 'Admin123!')
        project_id = create_project(client, creator, 'Phase 22 Wallet Dependency', 'P22W')
        challenge_id = create_challenge(client, creator, project_id, 'P22W', {
            'title': 'Verify an interactive-wallet transaction',
            'description': 'Complete the configured on-chain action from a verified interactive signer rather than a payout-only address.',
            'category': 'ONCHAIN',
            'provider': None,
            'action': None,
            'verification_type': 'AUTO',
            'target_id': '0x3333333333333333333333333333333333333333',
            'config': {
                'target_address': '0x3333333333333333333333333333333333333333',
                'calldata': '0x',
                'value_wei': '0',
                'chain': 'Avalanche',
            },
            'xp_reward': 50,
        })
        verify_funding(client, admin, challenge_id)

        user_id, participant = register(client, 'phase22-wallet-user@example.com', 'Phase22WalletUser')
        payout = client.post('/api/users/payout-addresses', headers=participant, json={
            'address': '0x4444444444444444444444444444444444444444',
            'chain': 'Avalanche',
            'label': 'Payout only',
            'make_primary': True,
        })
        assert payout.status_code == 200, payout.text

        detail = client.get(f'/api/challenges/{challenge_id}', headers=participant)
        assert detail.status_code == 200
        reqs = requirement_map(detail.json())
        assert reqs['INTERACTIVE_WALLET']['satisfied'] is False
        assert detail.json()['dependency_preflight']['interactive_wallet_address'] is None
        assert client.post(f'/api/challenges/{challenge_id}/join', headers=participant).status_code == 409

        with SessionLocal() as db:
            user = db.get(User, user_id)
            assert user.wallet_address == '0x4444444444444444444444444444444444444444'
            assert db.query(PayoutAddress).filter(PayoutAddress.user_id == user_id).count() == 1
            db.add(WalletConnection(
                user_id=user_id,
                address='0x5555555555555555555555555555555555555555',
                chain_type='ethereum',
                chain_id=43114,
                wallet_client_type='metamask',
                connector_type='injected',
                wallet_type='EXTERNAL',
                is_primary=False,
                is_primary_interactive=True,
                verified_at=datetime.now(UTC),
                last_connected_at=datetime.now(UTC),
            ))
            db.commit()

        ready = client.get(f'/api/challenges/{challenge_id}', headers=participant)
        assert ready.status_code == 200
        preflight = ready.json()['dependency_preflight']
        assert preflight['server_ready'] is True
        assert preflight['interactive_wallet_address'] == '0x5555555555555555555555555555555555555555'
        assert requirement_map(ready.json())['INTERACTIVE_WALLET']['satisfied'] is True
        joined = client.post(f'/api/challenges/{challenge_id}/join', headers=participant)
        assert joined.status_code == 200, joined.text


def test_swap_requirement_declares_live_signer_check_without_extra_nubagz_confirmation():
    challenge = Challenge(
        campaign_id=0,
        title='Use NuBagz Swap',
        description='Execute a swap with the verified wallet that is currently available to sign.',
        category='SWAP',
        provider='NUBAGZ_SWAP',
        action='SWAP',
        verification_type='AUTO',
    )
    codes = requirement_codes(challenge)
    assert 'INTERACTIVE_WALLET' in codes
    assert 'ACTIVE_SIGNER' in codes


def test_privy_social_sync_removes_supported_provider_that_is_no_longer_linked():
    with TestClient(app) as client:
        user_id, _ = register(client, 'phase22-sync-user@example.com', 'Phase22SyncUser')
        with SessionLocal() as db:
            user = db.get(User, user_id)
            first = sync_social_accounts(db, user, 'did:privy:phase22-sync', [
                {'type': 'twitter_oauth', 'subject': 'phase22-sync-x', 'username': 'phase22syncx'},
                {'type': 'google_oauth', 'subject': 'phase22-sync-google', 'email': 'phase22-sync-google@example.com'},
            ])
            db.commit()
            assert {row.provider for row in first} == {'X', 'GOOGLE'}

        with SessionLocal() as db:
            user = db.get(User, user_id)
            second = sync_social_accounts(db, user, 'did:privy:phase22-sync', [
                {'type': 'google_oauth', 'subject': 'phase22-sync-google', 'email': 'phase22-sync-google@example.com'},
            ])
            db.commit()
            assert {row.provider for row in second} == {'GOOGLE'}
            assert db.query(SocialAccount).filter(SocialAccount.user_id == user_id, SocialAccount.provider == 'X').count() == 0
