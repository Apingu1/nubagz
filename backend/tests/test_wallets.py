import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wallets.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-that-is-longer-than-thirty-two-bytes")

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from app.main import app


def auth(client):
    response=client.post('/api/auth/login',json={'email':'demo@demo.nubagz.com','password':'Demo123!'})
    assert response.status_code==200
    return {'Authorization':f"Bearer {response.json()['access_token']}"}


def test_payout_only_and_verified_wallet_paths_are_independent():
    Path('test_wallets.db').unlink(missing_ok=True)
    with TestClient(app) as client:
        headers=auth(client)
        payout=client.post('/api/users/payout-addresses',headers=headers,json={'address':'0x1111111111111111111111111111111111111111','chain':'Avalanche','label':'Cold reward wallet','make_primary':True})
        assert payout.status_code==200
        assert payout.json()['verification_status']=='UNVERIFIED'
        assert payout.json()['is_primary'] is True

        account=Account.create()
        challenge=client.post('/api/users/wallets/challenge',headers=headers,json={'address':account.address})
        assert challenge.status_code==200
        body=challenge.json()
        signature=Account.sign_message(encode_defunct(text=body['message']),account.key).signature.hex()
        verified=client.post('/api/users/wallets/verify',headers=headers,json={'challenge_id':body['challenge_id'],'address':account.address,'signature':signature,'wallet_client_type':'metamask','connector_type':'injected','chain_id':43114,'make_primary':True})
        assert verified.status_code==200
        assert verified.json()['verified_at'] is not None
        assert verified.json()['is_primary_interactive'] is True
        # The payout-only destination remains selected; signer selection is independent.
        assert verified.json()['is_primary'] is False

        wallet_id=verified.json()['id']
        reward_wallet=client.post(f'/api/users/wallets/{wallet_id}/primary',headers=headers)
        assert reward_wallet.status_code==200
        assert reward_wallet.json()['role']=='REWARD_DESTINATION'
        wallets=client.get('/api/users/wallets',headers=headers)
        assert wallets.status_code==200
        current=next(row for row in wallets.json() if row['id']==wallet_id)
        assert current['is_primary'] is True
        assert current['is_primary_interactive'] is True

        payout_again=client.post(f"/api/users/payout-addresses/{payout.json()['id']}/primary",headers=headers)
        assert payout_again.status_code==200
        wallets=client.get('/api/users/wallets',headers=headers).json()
        current=next(row for row in wallets if row['id']==wallet_id)
        assert current['is_primary'] is False
        assert current['is_primary_interactive'] is True
        payouts=client.get('/api/users/payout-addresses',headers=headers)
        assert payouts.status_code==200
        assert next(row for row in payouts.json() if row['id']==payout.json()['id'])['is_primary'] is True
