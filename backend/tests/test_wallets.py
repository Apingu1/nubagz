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


def test_payout_only_and_verified_wallet_paths():
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
        assert verified.json()['is_primary'] is True
        assert verified.json()['verified_at'] is not None
        assert client.get('/api/users/wallets',headers=headers).status_code==200
        assert client.get('/api/users/payout-addresses',headers=headers).status_code==200
