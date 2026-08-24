from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient

from app.main import app
import app.routers.challenges as challenge_router


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def register(client,email,username):
    r=client.post('/api/auth/register',json={'email':email,'username':username,'password':'CreatorFlow123!'});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def verify_wallet(client,headers,account):
    challenge=client.post('/api/users/wallets/challenge',headers=headers,json={'address':account.address});assert challenge.status_code==200
    sig=Account.sign_message(encode_defunct(text=challenge.json()['message']),account.key).signature.hex()
    verified=client.post('/api/users/wallets/verify',headers=headers,json={'challenge_id':challenge.json()['challenge_id'],'address':account.address,'signature':sig,'wallet_client_type':'metamask','connector_type':'injected','chain_id':43114,'make_primary':True})
    assert verified.status_code==200


def launch_payload(name,symbol,challenge,*,max_users=2,allocation=200,gross=100,gas=False):
    return {
        'project':{
            'name':name,'symbol':symbol,'description':'A complete creator launch used to prove the unified NuBagz project, Trust, Bag and Bag Work architecture.','website':'https://example.com','chain':'Avalanche','treasury_address':'0x2222222222222222222222222222222222222222'
        },
        'trust':{
            'contract_address':'0x1111111111111111111111111111111111111111','token_launch_date':'2026-08-01','docs_url':'https://example.com/docs','socials_url':'https://x.com/example','contract_source_verified':True,'dangerous_permissions_absent':True,'docs_verified':True,'socials_verified':True
        },
        'bag':{
            'project_id':0,'title':f'{name} Launch Rewards','description':'The first funded Bag is created inside the same guided launch and remains a draft until reward funding is verified.','category':'DISCOVER','difficulty':'EASY','reward_asset':symbol,'funding_type':'TOKEN','token_allocation':allocation,'gross_reward_per_user':gross,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':max_users,'missions':[],'challenges':[challenge]
        },
        'min_bag_score':250,
        'reward_funding':{'amount':allocation,'tx_hash':f'{symbol.lower()}-declared-funding'},
    }


def test_creator_launch_is_atomic_and_builds_project_trust_first_bag_work_access_and_funding():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!');admin=login(client,'admin@demo.nubagz.com','Admin123!')
        challenge={'title':'Read the launch guide','description':'Review the launch guide and submit a short proof note to the project.','category':'LEARN','verification_type':'PROJECT_REVIEW','config':{},'xp_reward':50}
        created=client.post('/api/creator/launch',headers=creator,json=launch_payload('Unified Creator Flow','UCFLOW',challenge))
        assert created.status_code==200
        out=created.json();pid=out['project_id'];cid=out['campaign_id']
        assert out['project_status']=='LIVE' and out['campaign_status']=='DRAFT'
        assert out['trust_status']=='SUBMITTED' and out['reward_funding_status']=='DECLARED'

        project=next(p for p in client.get('/api/projects/mine',headers=creator).json() if p['id']==pid)
        assert project['status']=='LIVE'
        bag=next(c for c in client.get('/api/campaigns/mine',headers=creator).json() if c['id']==cid)
        assert bag['status']=='DRAFT' and len(bag['challenges'])==1 and bag['challenges'][0]['title']=='Read the launch guide'
        trust=client.get(f'/api/trust/projects/{pid}',headers=creator);assert trust.status_code==200 and trust.json()['evidence']['status']=='SUBMITTED'
        access=client.get(f'/api/access/campaigns/{cid}',headers=creator);assert access.status_code==200 and access.json()['min_bag_score']==250
        funding=next(f for f in client.get('/api/funding/mine',headers=creator).json() if f['campaign_id']==cid)
        assert funding['status']=='DECLARED' and funding['fully_funded'] is False

        # Creator cannot publish until the objective reward funding gate passes.
        assert client.post(f'/api/campaigns/{cid}/publish',headers=creator).status_code==409
        verified=client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':200,'tx_hash':'ucflow-verified-funding'})
        assert verified.status_code==200 and verified.json()['fully_funded'] is True
        published=client.post(f'/api/campaigns/{cid}/publish',headers=creator);assert published.status_code==200 and published.json()['status']=='LIVE'

        # Force a failure after project/Bag records have been flushed: unsupported
        # gas chain must roll the entire launch back rather than leaving an orphan.
        failing_name='Atomic Rollback Project'
        bad_challenge={'title':'Unsupported sponsored transaction','description':'This deliberately invalid gas provider chain proves the whole creator launch rolls back.','category':'ONCHAIN','verification_type':'AUTO','target_id':'0x1111111111111111111111111111111111111111','config':{'target_address':'0x1111111111111111111111111111111111111111','calldata':'0x','value_wei':'0','chain':'Avalanche'},'xp_reward':10,'gas_sponsorship':{'enabled':True,'chain':'Solana','max_native_per_claim':0.01,'max_unique_users':10,'max_claims':10,'max_claims_per_wallet':1,'funded_amount':0.02,'funding_reference':'rollback-gas'}}
        failed=client.post('/api/creator/launch',headers=creator,json=launch_payload(failing_name,'ROLLBK',bad_challenge,max_users=1,allocation=10,gross=10))
        assert failed.status_code==400 and 'supports' in failed.json()['detail']
        assert all(p['name']!=failing_name for p in client.get('/api/projects/mine',headers=creator).json())


def test_unified_onchain_auto_verification_accepts_sponsored_or_user_paid_tx_hash_and_prevents_replay(monkeypatch):
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!');admin=login(client,'admin@demo.nubagz.com','Admin123!')
        target='0x1111111111111111111111111111111111111111';calldata='0x1234'
        challenge={'title':'Verified Avalanche action','description':'Complete the exact configured transaction and let NuBagz verify the chain result automatically.','category':'ONCHAIN','verification_type':'AUTO','target_id':target,'config':{'target_address':target,'calldata':calldata,'value_wei':'0','chain':'Avalanche'},'xp_reward':25}
        created=client.post('/api/creator/launch',headers=creator,json=launch_payload('Unified Onchain Flow','UONCH',challenge,max_users=2,allocation=20,gross=10));assert created.status_code==200
        cid=created.json()['campaign_id'];challenge_id=next(c for c in client.get('/api/campaigns/mine',headers=creator).json() if c['id']==cid)['challenges'][0]['id']
        assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':20,'tx_hash':'uonch-verified'}).status_code==200
        assert client.post(f'/api/campaigns/{cid}/publish',headers=creator).status_code==200

        first=register(client,'unified-onchain-one@example.com','UnifiedChainOne');account=Account.create();verify_wallet(client,first,account)
        second=register(client,'unified-onchain-two@example.com','UnifiedChainTwo');second_account=Account.create();verify_wallet(client,second,second_account)
        tx_hash='0x'+'ab'*32

        def fake_rpc(chain,method,params):
            assert chain=='Avalanche' and params==[tx_hash]
            if method=='eth_getTransactionReceipt':return {'status':'0x1'}
            if method=='eth_getTransactionByHash':return {'from':account.address,'to':target,'input':calldata,'value':'0x0'}
            raise AssertionError(method)
        monkeypatch.setattr(challenge_router,'rpc_call',fake_rpc)

        completed=client.post(f'/api/challenges/{challenge_id}/complete',headers=first,json={'answer':None,'evidence':tx_hash})
        assert completed.status_code==200 and completed.json()['status']=='VERIFIED' and completed.json()['completed'] is True

        # The same public transaction cannot be replayed by another NuBagz user.
        replay=client.post(f'/api/challenges/{challenge_id}/complete',headers=second,json={'answer':None,'evidence':tx_hash})
        assert replay.status_code in {400,409}
