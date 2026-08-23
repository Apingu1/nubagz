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


def test_challenge_scoped_gas_pass_reserves_atomically_and_provider_failure_spends_nothing():
    original_url=settings.gas_sponsor_provider_base_url;original_key=settings.gas_sponsor_provider_api_key
    settings.gas_sponsor_provider_base_url=None;settings.gas_sponsor_provider_api_key=None
    try:
        with TestClient(app) as client:
            creator=login(client,'creator@demo.nubagz.com','Creator123!');admin=login(client,'admin@demo.nubagz.com','Admin123!')
            user_res=client.post('/api/auth/register',json={'email':'feature24-user@example.com','username':'Feature24Gas','password':'GasPass123!'})
            assert user_res.status_code==200
            user={'Authorization':f"Bearer {user_res.json()['access_token']}"}
            account=Account.create();verify_wallet(client,user,account)

            project=client.post('/api/projects',headers=creator,json={'name':'Feature Twenty Four Gas','symbol':'GAS24','description':'An isolated project proving Gas Pass is optional project-funded sponsorship on one on-chain Bag Work activity.','chain':'Avalanche'})
            assert project.status_code==200 and project.json()['status']=='LIVE'
            pid=project.json()['id']

            campaign=client.post('/api/campaigns',headers=creator,json={
                'project_id':pid,'title':'Gas Sponsored Bag','description':'A funded Bag with one on-chain challenge carrying a deterministic project-funded Gas Pass.',
                'category':'DISCOVER','difficulty':'EASY','reward_asset':'GAS24','funding_type':'TOKEN','token_allocation':10,
                'gross_reward_per_user':10,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':1,
                'challenges':[{
                    'title':'Sponsored on-chain action','description':'Perform the configured contract action. Sponsorship is optional and challenge-scoped.',
                    'category':'ONCHAIN','verification_type':'PROJECT_REVIEW','target_id':'0x1111111111111111111111111111111111111111',
                    'config':{'target_address':'0x1111111111111111111111111111111111111111','calldata':'0x','value_wei':'0','chain':'Avalanche'},'xp_reward':10,
                    'gas_sponsorship':{'enabled':True,'chain':'Avalanche','max_native_per_claim':0.01,'max_unique_users':1,'max_claims':2,'max_claims_per_wallet':1,'funded_amount':0.02,'funding_reference':'feature24-declared'}
                }]
            })
            assert campaign.status_code==200 and campaign.json()['status']=='DRAFT'
            cid=campaign.json()['id']; challenge_id=campaign.json()['challenges'][0]['id']
            assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':10,'tx_hash':'feature24-campaign-funding'}).status_code==200
            assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':10,'tx_hash':'feature24-campaign-funding'}).status_code==200
            assert client.post(f'/api/campaigns/{cid}/publish',headers=creator).status_code==200

            policies=client.get('/api/gas/policies/admin',headers=admin);assert policies.status_code==200
            policy=next(p for p in policies.json() if p['challenge_id']==challenge_id);policy_id=policy['id']
            assert policy['funding_status']=='DECLARED' and policy['status']=='FUNDING_PENDING'
            insufficient=client.post(f'/api/gas/policies/{policy_id}/verify',headers=admin,json={'funded_amount':0.019,'funding_reference':'feature24-under'})
            assert insufficient.status_code==400
            activated=client.post(f'/api/gas/policies/{policy_id}/verify',headers=admin,json={'funded_amount':0.02,'funding_reference':'feature24-verified'})
            assert activated.status_code==200 and activated.json()['funding_status']=='VERIFIED' and activated.json()['status']=='ACTIVE'

            status=client.get(f'/api/gas/challenges/{challenge_id}',headers=user);assert status.status_code==200
            assert status.json()['mode']=='SPONSORED' and float(status.json()['max_sponsored_native'])==0.01

            prepared=client.post(f'/api/gas/challenges/{challenge_id}/prepare',headers=user,json={})
            assert prepared.status_code==200 and prepared.json()['mode']=='SPONSORED' and prepared.json()['status']=='RESERVED'
            claim_id=prepared.json()['claim_id']
            tx=prepared.json()['transaction']
            assert tx['to']=='0x1111111111111111111111111111111111111111' and tx['chainId']==43114

            # A second prepare for the same wallet is idempotent while the reservation is active.
            repeated=client.post(f'/api/gas/challenges/{challenge_id}/prepare',headers=user,json={})
            assert repeated.status_code==200 and repeated.json()['claim_id']==claim_id

            execution=client.post(f'/api/gas/claims/{claim_id}/execute',headers=user)
            assert execution.status_code==503 and 'no project gas budget was spent' in execution.json()['detail'].lower()
            row=next(p for p in client.get('/api/gas/policies/admin',headers=admin).json() if p['id']==policy_id)
            assert float(row['spent_amount'])==0 and row['executed_claims']==0 and row['reserved_claims']==1 and row['status']=='ACTIVE'

            # The old project-wide arbitrary-transaction Gas Pass endpoints are retired.
            assert client.post('/api/gas/budgets',headers=creator,json={'project_id':pid}).status_code==404
    finally:
        settings.gas_sponsor_provider_base_url=original_url;settings.gas_sponsor_provider_api_key=original_key
