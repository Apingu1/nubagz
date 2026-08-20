from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def register(client,email,username):
    r=client.post('/api/auth/register',json={'email':email,'username':username,'password':'Revenue123!'});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def balance(client,headers,asset):
    rows=client.get('/api/users/dashboard',headers=headers).json()['balances']
    return sum(float(r['amount']) for r in rows if r['asset_symbol']==asset)


def test_revenue_share_is_fixed_funded_snapshot_and_executes_once():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        u1=register(client,'feature13-a@example.com','Feature13A')
        u2=register(client,'feature13-b@example.com','Feature13B')

        project=client.post('/api/projects',headers=creator,json={'name':'Feature Thirteen Revenue','symbol':'BASE13','description':'An isolated project used to prove fixed funded community revenue distributions.','chain':'Avalanche'})
        assert project.status_code==200
        pid=project.json()['id']
        assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200
        campaign=client.post('/api/campaigns',headers=creator,json={
            'project_id':pid,'title':'Qualifying Contributor Bag','description':'Complete this funded Bag to enter the later fixed distribution snapshot.',
            'category':'LEARN','difficulty':'EASY','reward_asset':'BASE13','funding_type':'TOKEN','token_allocation':20,
            'gross_reward_per_user':10,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':2,
            'missions':[{'title':'Qualify','description':'Complete the contributor pathway','mission_type':'LEARN','verification_type':'SELF_ATTEST','xp_reward':10}]
        })
        assert campaign.status_code==200
        cid=campaign.json()['id']
        assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':20,'tx_hash':'feature13-campaign-funding'}).status_code==200
        assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':20,'tx_hash':'feature13-campaign-funding'}).status_code==200
        assert client.patch(f'/api/admin/campaigns/{cid}',headers=admin,json={'status':'LIVE'}).status_code==200
        mission=client.get(f'/api/campaigns/{cid}').json()['missions'][0]
        for headers in (u1,u2):
            assert client.post(f'/api/campaigns/{cid}/enroll',headers=headers).status_code==200
            done=client.post(f"/api/campaigns/{cid}/missions/{mission['id']}/complete",headers=headers,json={'answer':None})
            assert done.status_code==200 and done.json()['completed'] is True

        dist=client.post('/api/revenue-share',headers=creator,json={'campaign_id':cid,'title':'Realised community pool','asset_symbol':'REV13','funded_amount':100,'funding_reference':'feature13-declared-pool'})
        assert dist.status_code==200 and dist.json()['status']=='PENDING'
        assert dist.json()['funding_status']=='DECLARED'
        did=dist.json()['id']
        assert 'not a promised yield' in dist.json()['disclaimer'].lower()

        missing_verification=client.post(f'/api/revenue-share/{did}/activate',headers=admin)
        assert missing_verification.status_code==422
        activated=client.post(f'/api/revenue-share/{did}/activate',headers=admin,json={'funded_amount':100,'funding_reference':'feature13-verified-pool'})
        assert activated.status_code==200
        assert activated.json()['status']=='LIVE' and activated.json()['funding_status']=='VERIFIED'
        assert activated.json()['funding_reference']=='feature13-verified-pool'
        assert client.post(f'/api/revenue-share/{did}/activate',headers=admin,json={'funded_amount':100,'funding_reference':'feature13-verified-pool'}).status_code==409

        public_rows=client.get('/api/revenue-share',headers=u1)
        assert public_rows.status_code==200
        public_row=next(x for x in public_rows.json() if x['id']==did)
        assert 'funding_reference' not in public_row

        executed=client.post(f'/api/revenue-share/{did}/execute',headers=creator)
        assert executed.status_code==200
        out=executed.json()
        assert out['status']=='EXECUTED' and out['recipient_count']==2
        assert float(out['amount_per_recipient'])==50 and float(out['distributed_amount'])==100
        assert float(out['remaining_funded_amount'])==0
        assert balance(client,u1,'REV13')==50 and balance(client,u2,'REV13')==50
        assert client.post(f'/api/revenue-share/{did}/execute',headers=creator).status_code==409
