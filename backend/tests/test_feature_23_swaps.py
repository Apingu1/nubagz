from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings

USDG='0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168'
NATIVE='0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee'


def verify_wallet(client,headers,account):
    challenge=client.post('/api/users/wallets/challenge',headers=headers,json={'address':account.address});assert challenge.status_code==200
    sig=Account.sign_message(encode_defunct(text=challenge.json()['message']),account.key).signature.hex()
    verified=client.post('/api/users/wallets/verify',headers=headers,json={'challenge_id':challenge.json()['challenge_id'],'address':account.address,'signature':sig,'wallet_client_type':'metamask','connector_type':'injected','chain_id':4663,'make_primary':True})
    assert verified.status_code==200


def balances(client,headers):
    return client.get('/api/users/dashboard',headers=headers).json()['balances']


def test_swap_requires_verified_wallet_and_never_fabricates_execution_without_aggregators():
    original_0x=settings.zerox_api_key
    original_lifi=settings.lifi_api_key
    original_recipient=settings.nubagz_swap_fee_recipient
    settings.zerox_api_key=None
    settings.lifi_api_key=None
    settings.nubagz_swap_fee_recipient=None
    try:
        with TestClient(app) as client:
            user_res=client.post('/api/auth/register',json={'email':'feature23-user@example.com','username':'Feature23Swap','password':'Swaps123!'})
            assert user_res.status_code==200
            headers={'Authorization':f"Bearer {user_res.json()['access_token']}"}

            config=client.get('/api/swaps/config',headers=headers)
            assert config.status_code==200
            cfg=config.json()
            assert cfg['primary_chain']=='Robinhood'
            assert cfg['chains'][0]['chain_id']==4663 and cfg['chains'][0]['native_symbol']=='ETH'
            assert cfg['fee_bps']==settings.swap_fee_bps==75
            assert cfg['ready'] is False and cfg['providers']=={'0x':False,'LI.FI':False}
            assert 'never has custody' in cfg['execution_model']

            blocked=client.post('/api/swaps/quote',headers=headers,json={'chain':'Robinhood','sell_token':NATIVE,'buy_token':USDG,'sell_amount':'1000000000000000','slippage_bps':100})
            assert blocked.status_code==400 and 'verify' in blocked.json()['detail'].lower()

            account=Account.create();verify_wallet(client,headers,account)
            before=balances(client,headers)
            no_route=client.post('/api/swaps/quote',headers=headers,json={'chain':'Robinhood','sell_token':NATIVE,'buy_token':USDG,'sell_amount':'1000000000000000','slippage_bps':100})
            assert no_route.status_code==503
            assert 'no executable fee-enabled swap route' in no_route.json()['detail'].lower()
            after=balances(client,headers)
            assert after==before
            history=client.get('/api/swaps/history',headers=headers)
            assert history.status_code==200 and history.json()==[]
    finally:
        settings.zerox_api_key=original_0x
        settings.lifi_api_key=original_lifi
        settings.nubagz_swap_fee_recipient=original_recipient
