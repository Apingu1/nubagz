from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def asset_balance(client, headers, asset):
    rows=client.get('/api/users/dashboard',headers=headers).json()['balances']
    return sum(float(r['amount']) for r in rows if r['asset_symbol']==asset)


def treasury_balance(client, headers, asset):
    rows=client.get('/api/admin/treasury',headers=headers).json()
    return sum(float(r['amount']) for r in rows if r['asset']==asset)


def test_bagbuilder_api_is_retired_and_platform_share_is_not_diverted():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        former_builder=login(client,'demo@demo.nubagz.com','Demo123!')
        participant_res=client.post('/api/auth/register',json={'email':'feature11-user@example.com','username':'Feature11User','password':'Builder123!'})
        assert participant_res.status_code==200
        participant={'Authorization':f"Bearer {participant_res.json()['access_token']}"}

        project=client.post('/api/projects',headers=creator,json={'name':'Feature Eleven Simplified Economy','symbol':'BUILD11','description':'An isolated project proving community BagBuilder attribution has been retired from active settlement.','chain':'Avalanche'})
        assert project.status_code==200 and project.json()['status']=='LIVE'
        pid=project.json()['id']
        campaign=client.post('/api/campaigns',headers=creator,json={
            'project_id':pid,'title':'Direct Participation Bag','description':'A funded campaign that settles only the user, NuBagz platform and referral/community shares.',
            'category':'LEARN','difficulty':'EASY','reward_asset':'BUILD11','funding_type':'TOKEN','token_allocation':100,
            'gross_reward_per_user':100,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':1,
            'missions':[{'title':'Complete direct route','description':'Finish the creator-defined activity without a community pathway layer.','mission_type':'LEARN','verification_type':'SELF_ATTEST','xp_reward':10}]
        })
        assert campaign.status_code==200 and campaign.json()['status']=='DRAFT'
        cid=campaign.json()['id']
        assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':100,'tx_hash':'feature11-funding'}).status_code==200
        assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':100,'tx_hash':'feature11-funding'}).status_code==200
        assert client.post(f'/api/campaigns/{cid}/publish',headers=creator).status_code==200

        # The old community pathway product is intentionally no longer registered.
        retired=client.post('/api/builders',headers=former_builder,json={'campaign_id':cid,'title':'Old pathway','summary':'This old pathway endpoint must no longer be available to create creator spam.','creator_share_pct':5})
        assert retired.status_code==404
        assert client.get('/api/builders/stats',headers=former_builder).status_code==404

        assert client.post(f'/api/campaigns/{cid}/enroll',headers=participant).status_code==200
        mission=client.get(f'/api/campaigns/{cid}').json()['missions'][0]
        complete=client.post(f"/api/campaigns/{cid}/missions/{mission['id']}/complete",headers=participant,json={'answer':None})
        assert complete.status_code==200 and complete.json()['completed'] is True

        assert asset_balance(client, participant, 'BUILD11')==80
        assert asset_balance(client, former_builder, 'BUILD11')==0
        # 15% NuBagz platform share + the unassigned 5% referral/community share.
        assert treasury_balance(client, admin, 'BUILD11')==20
