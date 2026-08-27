import json

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.db import SessionLocal
from app.integration_models import SwapTrade
from app.models import WalletConnection
from app.routers import swaps as swaps_router

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
    original_integrator=settings.lifi_integrator
    original_recipient=settings.nubagz_swap_fee_recipient
    settings.zerox_api_key=None
    settings.lifi_api_key=None
    settings.lifi_integrator=''
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
            assert 'no executable fee-enabled route' in no_route.json()['detail'].lower()
            after=balances(client,headers)
            assert after==before
            history=client.get('/api/swaps/history',headers=headers)
            assert history.status_code==200 and history.json()==[]
    finally:
        settings.zerox_api_key=original_0x
        settings.lifi_api_key=original_lifi
        settings.lifi_integrator=original_integrator
        settings.nubagz_swap_fee_recipient=original_recipient


def test_lifi_public_quote_does_not_require_api_key(monkeypatch):
    original_key=settings.lifi_api_key
    original_integrator=settings.lifi_integrator
    settings.lifi_api_key=None
    settings.lifi_integrator='nubagz'
    captured={}

    class Response:
        status_code=200
        text=''
        def raise_for_status(self): return None
        def json(self):
            return {
                'id':'public-lifi-quote',
                'estimate':{'toAmount':'990000','toAmountMin':'980000','approvalAddress':None,'gasCosts':[],'feeCosts':[{'name':'integrator fee','amount':'7500'}]},
                'transactionRequest':{'from':captured['wallet'],'to':'0x1111111111111111111111111111111111111111','chainId':4663,'data':'0x1234','value':'0x0'},
                'tool':'test-dex',
            }

    def fake_get(url,params=None,headers=None,timeout=None):
        assert url=='https://li.quest/v1/quote'
        captured['headers']=headers
        captured['params']=params
        return Response()

    monkeypatch.setattr(swaps_router.httpx,'get',fake_get)
    try:
        with TestClient(app) as client:
            user_res=client.post('/api/auth/register',json={'email':'feature23-public-lifi@example.com','username':'Feature23PublicLifi','password':'Swaps123!'})
            headers={'Authorization':f"Bearer {user_res.json()['access_token']}"}
            account=Account.create();verify_wallet(client,headers,account);captured['wallet']=account.address
            config=client.get('/api/swaps/config',headers=headers).json()
            assert config['providers']['LI.FI'] is True
            assert config['provider_auth']['LI.FI']=='PUBLIC_RATE_LIMIT'
            route=swaps_router._quote_lifi(swaps_router.CHAINS['robinhood'],NATIVE,USDG,'1000000000000000',100,SessionWallet(account.address))
            assert route['provider']=='LI.FI' and route['buy_amount']=='990000'
            assert 'x-lifi-api-key' not in captured['headers']
            assert captured['params']['fee']=='0.0075'
    finally:
        settings.lifi_api_key=original_key
        settings.lifi_integrator=original_integrator


class SessionWallet:
    def __init__(self,address):
        self.address=address


def test_confirmed_swap_is_bound_to_exact_server_quote_and_raw_amounts_are_precision_safe(monkeypatch):
    with TestClient(app) as client:
        user_res=client.post('/api/auth/register',json={'email':'feature23-receipt@example.com','username':'Feature23Receipt','password':'Swaps123!'})
        assert user_res.status_code==200
        headers={'Authorization':f"Bearer {user_res.json()['access_token']}"}
        user_id=user_res.json()['user']['id']
        account=Account.create();verify_wallet(client,headers,account)

        db=SessionLocal()
        try:
            wallet=db.query(WalletConnection).filter(WalletConnection.user_id==user_id,WalletConnection.verified_at.isnot(None)).first()
            assert wallet is not None
            huge_raw='1000000000000000000000000000000'
            expected_to='0x1111111111111111111111111111111111111111'
            route={
                'provider':'test-router',
                'buy_amount':'2500000',
                'min_buy_amount':'2400000',
                'transaction':{'to':expected_to,'data':'0x1234','value':'0x0','chainId':4663},
            }
            row=SwapTrade(
                user_id=user_id,
                wallet_connection_id=wallet.id,
                chain='Robinhood',
                chain_id=4663,
                sell_asset=NATIVE,
                buy_asset=USDG,
                sell_amount_raw=huge_raw,
                quoted_buy_amount_raw='2500000',
                max_slippage_bps=100,
                status='QUOTED',
                provider_name='test-router',
                provider_quote_id='test-quote',
                transaction_payload=json.dumps(route,separators=(',',':')),
            )
            db.add(row);db.commit();db.refresh(row);session_id=row.id
        finally:
            db.close()

        bad_hash='0x'+'1'*64
        good_hash='0x'+'2'*64

        def fake_rpc(chain,method,params):
            tx_hash=params[0]
            if method=='eth_getTransactionReceipt':
                return {'status':'0x1','blockNumber':'0x10','gasUsed':'0x5208','effectiveGasPrice':'0x1','logs':[]}
            if method=='eth_getTransactionByHash':
                return {
                    'from':account.address,
                    'to':expected_to,
                    'input':'0xabcd' if tx_hash==bad_hash else '0x1234',
                    'value':'0x0',
                }
            raise AssertionError(method)

        monkeypatch.setattr(swaps_router,'rpc_call',fake_rpc)

        mismatch=client.post('/api/swaps/confirm',headers=headers,json={'session_id':session_id,'tx_hash':bad_hash})
        assert mismatch.status_code==400
        assert 'calldata' in mismatch.json()['detail'].lower()

        confirmed=client.post('/api/swaps/confirm',headers=headers,json={'session_id':session_id,'tx_hash':good_hash})
        assert confirmed.status_code==200
        assert confirmed.json()['status']=='CONFIRMED' and confirmed.json()['confirmed'] is True
        assert confirmed.json()['quoted_buy_amount']=='2500000'

        history=client.get('/api/swaps/history',headers=headers)
        assert history.status_code==200
        row=next(item for item in history.json() if item['session_id']==session_id)
        assert row['sell_amount']==huge_raw
        assert row['quoted_buy_amount']=='2500000'
        assert row['tx_hash']==good_hash
