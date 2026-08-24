from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from app.main import app
from app.routers import onchain as onchain_router


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
        'wallet_client_type': 'metamask', 'connector_type': 'injected', 'chain_id': 43114, 'make_primary': True
    })
    assert verified.status_code == 200


def test_onchain_rule_is_authoritative_frozen_and_tx_cannot_be_reused():
    with TestClient(app) as client:
        creator = login(client, 'creator@demo.nubagz.com', 'Creator123!')
        earner = login(client, 'demo@demo.nubagz.com', 'Demo123!')
        account = Account.create()
        verify_wallet(client, earner, account)
        # The legacy /onchain router remains only for compatibility. New unified
        # Bag Work campaigns may contain no legacy missions, so select a seeded
        # campaign that actually has one rather than assuming list position zero.
        campaigns = client.get('/api/campaigns/mine', headers=creator).json()
        campaign = next(c for c in campaigns if c['missions'])
        mission_id = campaign['missions'][0]['id']

        unsupported = client.post('/api/onchain/rules', headers=creator, json={
            'mission_id': mission_id, 'chain': 'UnknownChain', 'rule_type': 'TX_SUCCESS'
        })
        assert unsupported.status_code == 400

        rule = client.post('/api/onchain/rules', headers=creator, json={
            'mission_id': mission_id, 'chain': 'Avalanche', 'rule_type': 'TX_SUCCESS'
        })
        assert rule.status_code == 200
        rule_id = rule.json()['id']

        original_rpc = onchain_router.rpc_call
        def fake_rpc(chain, method, params):
            assert chain.lower() == 'avalanche'
            if method == 'eth_getTransactionReceipt':
                return {'status': '0x1'}
            if method == 'eth_getTransactionByHash':
                return {'from': account.address, 'to': '0x2222222222222222222222222222222222222222'}
            raise AssertionError(method)
        onchain_router.rpc_call = fake_rpc
        try:
            proof = client.post(f'/api/onchain/rules/{rule_id}/verify', headers=earner, json={'tx_hash': '0xfeature06tx'})
            assert proof.status_code == 200
            frozen = client.post('/api/onchain/rules', headers=creator, json={
                'mission_id': mission_id, 'chain': 'Avalanche', 'rule_type': 'NATIVE_BALANCE', 'min_amount': 1
            })
            assert frozen.status_code == 409

            second = client.post('/api/auth/register', json={
                'email': 'feature06-second@example.com', 'username': 'Feature06Second', 'password': 'Onchain123!'
            })
            assert second.status_code == 200
            second_headers = {'Authorization': f"Bearer {second.json()['access_token']}"}
            verify_wallet(client, second_headers, account)
            replay = client.post(f'/api/onchain/rules/{rule_id}/verify', headers=second_headers, json={'tx_hash': '0xfeature06tx'})
            assert replay.status_code == 409
        finally:
            onchain_router.rpc_call = original_rpc
