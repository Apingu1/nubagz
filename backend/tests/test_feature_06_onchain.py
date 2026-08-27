from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient

from app.main import app
from app.routers import challenges as challenges_router


def login(client, email, password):
    r = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200
    return {'Authorization': f"Bearer {r.json()['access_token']}"}


def verify_wallet(client, headers, account):
    challenge = client.post('/api/users/wallets/challenge', headers=headers, json={'address': account.address})
    assert challenge.status_code == 200
    sig = Account.sign_message(encode_defunct(text=challenge.json()['message']), account.key).signature.hex()
    verified = client.post('/api/users/wallets/verify', headers=headers, json={
        'challenge_id': challenge.json()['challenge_id'], 'address': account.address, 'signature': sig,
        'wallet_client_type': 'metamask', 'connector_type': 'injected', 'chain_id': 4663, 'make_primary': True
    })
    assert verified.status_code == 200


def test_unified_onchain_challenge_is_authoritative_and_tx_cannot_be_reused():
    with TestClient(app) as client:
        creator = login(client, 'creator@demo.nubagz.com', 'Creator123!')
        admin = login(client, 'admin@demo.nubagz.com', 'Admin123!')
        first = client.post('/api/auth/register', json={
            'email': 'feature06-first@example.com', 'username': 'Feature06First', 'password': 'Onchain123!'
        })
        second = client.post('/api/auth/register', json={
            'email': 'feature06-second@example.com', 'username': 'Feature06Second', 'password': 'Onchain123!'
        })
        assert first.status_code == 200 and second.status_code == 200
        first_h = {'Authorization': f"Bearer {first.json()['access_token']}"}
        second_h = {'Authorization': f"Bearer {second.json()['access_token']}"}
        first_account = Account.create()
        second_account = Account.create()
        verify_wallet(client, first_h, first_account)
        verify_wallet(client, second_h, second_account)

        project = client.post('/api/projects', headers=creator, json={
            'name': 'Feature Six Unified Onchain', 'symbol': 'ONC06',
            'description': 'Isolated Robinhood Chain project proving authoritative transaction verification and replay protection.',
            'chain': 'Robinhood'
        })
        assert project.status_code == 200
        pid = project.json()['id']
        target = '0x1111111111111111111111111111111111111111'
        bag = client.post('/api/campaigns', headers=creator, json={
            'project_id': pid, 'title': 'Robinhood transaction proof Bag',
            'description': 'Complete one fixed Robinhood Chain transaction and prove it from the verified participant wallet.',
            'category': 'LEARN', 'difficulty': 'EASY', 'reward_asset': 'ONC06', 'funding_type': 'TOKEN',
            'token_allocation': 2, 'gross_reward_per_user': 1, 'user_share_pct': 80, 'nubagz_share_pct': 15,
            'referral_share_pct': 5, 'max_users': 2, 'missions': [],
            'challenges': [{
                'title': 'Execute Robinhood transaction',
                'description': 'Send the configured zero-value interaction from your verified wallet.',
                'category': 'ONCHAIN', 'verification_type': 'AUTO', 'target_id': target,
                'config': {'chain': 'Robinhood', 'target_address': target, 'calldata': '0x', 'value_wei': '0'},
                'xp_reward': 10
            }]
        })
        assert bag.status_code == 200 and bag.json()['status'] == 'DRAFT'
        cid = bag.json()['id']
        challenge_id = bag.json()['challenges'][0]['id']
        assert client.post(f'/api/funding/campaigns/{cid}/declare', headers=creator, json={'amount': 2, 'tx_hash': 'feature06-funding'}).status_code == 200
        assert client.post(f'/api/funding/campaigns/{cid}/verify', headers=admin, json={'amount': 2, 'tx_hash': 'feature06-funding'}).status_code == 200
        assert client.post(f'/api/campaigns/{cid}/publish', headers=creator).status_code == 200
        assert client.post(f'/api/campaigns/{cid}/enroll', headers=first_h).status_code == 200
        assert client.post(f'/api/campaigns/{cid}/enroll', headers=second_h).status_code == 200

        tx_hash = '0x' + 'ab' * 32
        original_rpc = challenges_router.rpc_call
        active_sender = {'address': first_account.address}

        def fake_rpc(chain, method, params):
            assert chain.lower() == 'robinhood'
            if method == 'eth_getTransactionReceipt':
                return {'status': '0x1'}
            if method == 'eth_getTransactionByHash':
                return {'from': active_sender['address'], 'to': target, 'input': '0x', 'value': '0x0'}
            raise AssertionError(method)

        challenges_router.rpc_call = fake_rpc
        try:
            proof = client.post(f'/api/challenges/{challenge_id}/complete', headers=first_h, json={'evidence': tx_hash})
            assert proof.status_code == 200
            assert proof.json()['completed'] is True and proof.json()['status'] == 'VERIFIED'

            active_sender['address'] = second_account.address
            replay = client.post(f'/api/challenges/{challenge_id}/complete', headers=second_h, json={'evidence': tx_hash})
            assert replay.status_code == 409
            assert 'already been used' in replay.json()['detail']
        finally:
            challenges_router.rpc_call = original_rpc
