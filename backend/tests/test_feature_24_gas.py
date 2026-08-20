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


def test_sponsored_gas_requires_independent_full_project_funding_and_provider_failure_spends_nothing():
    original_url=settings.gas_sponsor_provider_base_url;original_key=settings.gas_sponsor_provider_api_key
    settings.gas_sponsor_provider_base_url=None;settings.gas_sponsor_provider_api_key=None
    try:
        with TestClient(app) as client:
            creator=login(client,'creator@demo.nubagz.com','Creator123!');admin=login(client,'admin@demo.nubagz.com','Admin123!')
            user_res=client.post('/api/auth/register',json={'email':'feature24-user@example.com','username':'Feature24Gas','password':'GasPass123!'})
            assert user_res.status_code==200
            user={'Authorization':f"Bearer {user_res.json()['access_token']}"}
            account=Account.create();verify_wallet(client,user,account)

            project=client.post('/api/projects',headers=creator,json={'name':'Feature Twenty Four Gas','symbol':'GAS24','description':'An isolated project used to prove sponsored gas is project funded and never falls back to founder money.','chain':'Avalanche'});assert project.status_code==200
            pid=project.json()['id'];assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200
            campaign=client.post('/api/campaigns',headers=creator,json={'project_id':pid,'title':'Gas Sponsored Bag','description':'A funded Bag whose joined participant can request a separate sponsor-funded gas allowance.','category':'DISCOVER','difficulty':'EASY','reward_asset':'GAS24','funding_type':'TOKEN','token_allocation':10,'gross_reward_per_user':10,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':1,'missions':[{'title':'Discover','description':'Join the gas sponsored pathway','mission_type':'DISCOVER','verification_type':'SELF_ATTEST','xp_reward':10}]});assert campaign.status_code==200
            cid=campaign.json()['id'];assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':10,'tx_hash':'feature24-campaign-funding'}).status_code==200;assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':10,'tx_hash':'feature24-campaign-funding'}).status_code==200;assert client.patch(f'/api/admin/campaigns/{cid}',headers=admin,json={'status':'LIVE'}).status_code==200;assert client.post(f'/api/campaigns/{cid}/enroll',headers=user).status_code==200

            under=client.post('/api/gas/budgets',headers=creator,json={'project_id':pid,'chain':'Avalanche','amount_per_tx':0.01,'max_transactions':2,'funded_amount':0.019,'funding_reference':'feature24-under'})
            assert under.status_code==400 and 'maximum obligation' in under.json()['detail']
            budget=client.post('/api/gas/budgets',headers=creator,json={'project_id':pid,'chain':'Avalanche','amount_per_tx':0.01,'max_transactions':2,'funded_amount':0.02,'funding_reference':'feature24-declared'})
            assert budget.status_code==200 and budget.json()['status']=='PENDING' and budget.json()['funding_status']=='DECLARED'
            bid=budget.json()['id']
            insufficient=client.post(f'/api/gas/budgets/{bid}/activate',headers=admin,json={'funded_amount':0.019,'funding_reference':'feature24-verified-under'})
            assert insufficient.status_code==400
            activated=client.post(f'/api/gas/budgets/{bid}/activate',headers=admin,json={'funded_amount':0.02,'funding_reference':'feature24-verified'})
            assert activated.status_code==200 and activated.json()['funding_status']=='VERIFIED' and activated.json()['status']=='LIVE'
            assert client.post(f'/api/gas/budgets/{bid}/activate',headers=admin,json={'funded_amount':0.02,'funding_reference':'feature24-repeat'}).status_code==409

            bad_tx=client.post(f'/api/gas/budgets/{bid}/requests',headers=user,json={'campaign_id':cid,'transaction':{'to':'0x1234','data':'0x','value':'0x0'}})
            assert bad_tx.status_code==400
            request=client.post(f'/api/gas/budgets/{bid}/requests',headers=user,json={'campaign_id':cid,'transaction':{'to':'0x1111111111111111111111111111111111111111','data':'0x','value':'0x0','chainId':43114}})
            assert request.status_code==200 and request.json()['status']=='DRAFT'
            rid=request.json()['id']
            execution=client.post(f'/api/gas/requests/{rid}/execute',headers=user)
            assert execution.status_code==503 and 'no sponsor budget was spent' in execution.json()['detail'].lower()
            row=next(b for b in client.get('/api/gas/budgets/admin',headers=admin).json() if b['id']==bid)
            assert float(row['spent_amount'])==0 and row['executed_transactions']==0 and row['remaining_transactions']==2 and row['status']=='LIVE'
            req=next(r for r in client.get('/api/gas/requests',headers=user).json() if r['id']==rid)
            assert req['status']=='DRAFT' and req['tx_hash'] is None and req['gas_spent_native'] is None
    finally:
        settings.gas_sponsor_provider_base_url=original_url;settings.gas_sponsor_provider_api_key=original_key
