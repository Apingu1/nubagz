from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def register(client,email,username):
    r=client.post('/api/auth/register',json={'email':email,'username':username,'password':'GasPass123!'});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def verify_wallet(client,headers,account):
    challenge=client.post('/api/users/wallets/challenge',headers=headers,json={'address':account.address});assert challenge.status_code==200
    sig=Account.sign_message(encode_defunct(text=challenge.json()['message']),account.key).signature.hex()
    verified=client.post('/api/users/wallets/verify',headers=headers,json={'challenge_id':challenge.json()['challenge_id'],'address':account.address,'signature':sig,'wallet_client_type':'metamask','connector_type':'injected','chain_id':43114,'make_primary':True})
    assert verified.status_code==200


def test_challenge_scoped_gas_pass_reserves_atomically_budget_can_end_first_and_provider_failure_spends_nothing():
    original_url=settings.gas_sponsor_provider_base_url;original_key=settings.gas_sponsor_provider_api_key
    settings.gas_sponsor_provider_base_url=None;settings.gas_sponsor_provider_api_key=None
    try:
        with TestClient(app) as client:
            creator=login(client,'creator@demo.nubagz.com','Creator123!');admin=login(client,'admin@demo.nubagz.com','Admin123!')
            user=register(client,'feature24-user@example.com','Feature24Gas');verify_wallet(client,user,Account.create())
            second=register(client,'feature24-second@example.com','Feature24Second');verify_wallet(client,second,Account.create())

            project=client.post('/api/projects',headers=creator,json={'name':'Feature Twenty Four Gas','symbol':'GAS24','description':'An isolated project proving Gas Pass is optional project-funded sponsorship on one on-chain Bag Work activity.','chain':'Avalanche'})
            assert project.status_code==200 and project.json()['status']=='LIVE';pid=project.json()['id']
            campaign=client.post('/api/campaigns',headers=creator,json={
                'project_id':pid,'title':'Gas Sponsored Bag','description':'A funded Bag with one on-chain challenge carrying a deterministic project-funded Gas Pass.',
                'category':'DISCOVER','difficulty':'EASY','reward_asset':'GAS24','funding_type':'TOKEN','token_allocation':20,
                'gross_reward_per_user':10,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':2,
                'challenges':[{
                    'title':'Sponsored on-chain action','description':'Perform the configured contract action. Sponsorship is optional and challenge-scoped.',
                    'category':'ONCHAIN','verification_type':'AUTO','target_id':'0x1111111111111111111111111111111111111111',
                    'config':{'target_address':'0x1111111111111111111111111111111111111111','calldata':'0x','value_wei':'0','chain':'Avalanche'},'xp_reward':10,
                    'gas_sponsorship':{'enabled':True,'chain':'Avalanche','max_native_per_claim':0.01,'max_unique_users':1,'max_claims':100,'max_claims_per_wallet':1,'funded_amount':0.005,'funding_reference':'feature24-declared'}
                }]
            })
            assert campaign.status_code==200 and campaign.json()['status']=='DRAFT'
            cid=campaign.json()['id'];challenge_id=campaign.json()['challenges'][0]['id']
            assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':20,'tx_hash':'feature24-campaign-funding'}).status_code==200
            assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':20,'tx_hash':'feature24-campaign-funding'}).status_code==200
            assert client.post(f'/api/campaigns/{cid}/publish',headers=creator).status_code==200

            policy=next(p for p in client.get('/api/gas/policies/admin',headers=admin).json() if p['challenge_id']==challenge_id);policy_id=policy['id']
            assert policy['funding_status']=='DECLARED' and policy['status']=='FUNDING_PENDING'
            # Total budget is allowed to be lower than per-claim cap × max claims.
            activated=client.post(f'/api/gas/policies/{policy_id}/verify',headers=admin,json={'funded_amount':0.005,'funding_reference':'feature24-verified'})
            assert activated.status_code==200 and activated.json()['funding_status']=='VERIFIED' and activated.json()['status']=='ACTIVE'

            status=client.get(f'/api/gas/challenges/{challenge_id}',headers=user);assert status.status_code==200
            assert status.json()['mode']=='SPONSORED' and float(status.json()['max_sponsored_native'])==0.005
            prepared=client.post(f'/api/gas/challenges/{challenge_id}/prepare',headers=user,json={})
            assert prepared.status_code==200 and prepared.json()['mode']=='SPONSORED' and prepared.json()['status']=='RESERVED'
            claim_id=prepared.json()['claim_id'];assert float(prepared.json()['reserved_native_amount'])==0.005
            tx=prepared.json()['transaction'];assert tx['to']=='0x1111111111111111111111111111111111111111' and tx['chainId']==43114

            # Repeated prepare is idempotent and does not consume another slot/budget reservation.
            repeated=client.post(f'/api/gas/challenges/{challenge_id}/prepare',headers=user,json={})
            assert repeated.status_code==200 and repeated.json()['claim_id']==claim_id

            # max_unique_users=1 is deterministic: another eligible wallet falls back to user-paid gas.
            no_slot=client.post(f'/api/gas/challenges/{challenge_id}/prepare',headers=second,json={})
            assert no_slot.status_code==200 and no_slot.json()['mode']=='USER_PAID' and no_slot.json()['reason']=='USER_LIMIT_REACHED'
            assert no_slot.json()['transaction']['to']=='0x1111111111111111111111111111111111111111'

            execution=client.post(f'/api/gas/claims/{claim_id}/execute',headers=user)
            assert execution.status_code==503 and 'no project gas budget was spent' in execution.json()['detail'].lower()
            row=next(p for p in client.get('/api/gas/policies/admin',headers=admin).json() if p['id']==policy_id)
            assert float(row['spent_amount'])==0 and row['executed_claims']==0 and row['reserved_claims']==1 and row['status']=='ACTIVE'
            assert client.post('/api/gas/budgets',headers=creator,json={'project_id':pid}).status_code==404
    finally:
        settings.gas_sponsor_provider_base_url=original_url;settings.gas_sponsor_provider_api_key=original_key
