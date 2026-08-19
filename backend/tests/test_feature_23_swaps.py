from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def verify_wallet(client,headers,account):
    challenge=client.post('/api/users/wallets/challenge',headers=headers,json={'address':account.address});assert challenge.status_code==200
    sig=Account.sign_message(encode_defunct(text=challenge.json()['message']),account.key).signature.hex()
    verified=client.post('/api/users/wallets/verify',headers=headers,json={'challenge_id':challenge.json()['challenge_id'],'address':account.address,'signature':sig,'wallet_client_type':'metamask','connector_type':'injected','chain_id':43114,'make_primary':True})
    assert verified.status_code==200


def balances(client,headers):
    return client.get('/api/users/dashboard',headers=headers).json()['balances']


def test_swap_draft_requires_verified_wallet_and_unconfigured_provider_moves_nothing():
    original_url=settings.swap_provider_base_url;original_key=settings.swap_provider_api_key
    settings.swap_provider_base_url=None;settings.swap_provider_api_key=None
    try:
        with TestClient(app) as client:
            user_res=client.post('/api/auth/register',json={'email':'feature23-user@example.com','username':'Feature23Swap','password':'Swaps123!'})
            assert user_res.status_code==200
            headers={'Authorization':f"Bearer {user_res.json()['access_token']}"}
            blocked=client.post('/api/swaps/intents',headers=headers,json={'chain':'Avalanche','sell_asset':'USDC','buy_asset':'AVAX','sell_amount':10,'max_slippage_bps':100})
            assert blocked.status_code==400 and 'verify' in blocked.json()['detail'].lower()

            account=Account.create();verify_wallet(client,headers,account)
            before=balances(client,headers)
            status=client.get('/api/swaps/status',headers=headers);assert status.status_code==200
            assert status.json()['configured'] is False and status.json()['mode']=='DRAFT_ONLY'
            draft=client.post('/api/swaps/intents',headers=headers,json={'chain':'Avalanche','sell_asset':'USDC','buy_asset':'AVAX','sell_amount':10,'max_slippage_bps':100})
            assert draft.status_code==200 and draft.json()['status']=='DRAFT'
            intent_id=draft.json()['id']
            quote=client.post(f'/api/swaps/intents/{intent_id}/quote',headers=headers)
            assert quote.status_code==503 and 'no funds were moved' in quote.json()['detail'].lower()
            after=balances(client,headers)
            assert after==before
            row=next(x for x in client.get('/api/swaps/intents',headers=headers).json() if x['id']==intent_id)
            assert row['status']=='DRAFT' and row['provider_quote_id'] is None and row['transaction_payload'] is None
    finally:
        settings.swap_provider_base_url=original_url;settings.swap_provider_api_key=original_key
