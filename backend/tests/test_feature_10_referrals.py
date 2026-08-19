from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def earnings_for(payload, asset):
    return sum(float(row['amount']) for row in payload['earnings'] if row['asset']==asset)


def test_referral_signup_is_free_and_reward_only_follows_funded_conversion():
    with TestClient(app) as client:
        referrer=login(client,'demo@demo.nubagz.com','Demo123!')
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        before=client.get('/api/referrals/me',headers=referrer);assert before.status_code==200
        code=before.json()['referral_code'];count=before.json()['referred_users'];before_reward=earnings_for(before.json(),'REF10')

        created=client.post('/api/auth/register',json={'email':'feature10-ref@example.com','username':'Feature10Ref','password':'Referral123!','referral_code':code})
        assert created.status_code==200
        referred={'Authorization':f"Bearer {created.json()['access_token']}"}
        after_signup=client.get('/api/referrals/me',headers=referrer)
        assert after_signup.json()['referred_users']==count+1
        assert earnings_for(after_signup.json(),'REF10')==before_reward

        project=client.post('/api/projects',headers=creator,json={'name':'Feature Ten Referrals','symbol':'REF10','description':'An isolated funded project used to prove performance based referral economics.','chain':'Avalanche'})
        assert project.status_code==200
        pid=project.json()['id']
        assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200
        campaign=client.post('/api/campaigns',headers=creator,json={
            'project_id':pid,'title':'Referral Conversion Bag','description':'A funded one-step Bag used to validate referral economics after real participation.',
            'category':'LEARN','difficulty':'EASY','reward_asset':'REF10','funding_type':'TOKEN','token_allocation':100,
            'gross_reward_per_user':100,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':1,
            'missions':[{'title':'Participate','description':'Complete the funded referral pathway','mission_type':'LEARN','verification_type':'SELF_ATTEST','xp_reward':10}]
        })
        assert campaign.status_code==200
        cid=campaign.json()['id']
        assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':100,'tx_hash':'feature10-funding'}).status_code==200
        assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':100,'tx_hash':'feature10-funding'}).status_code==200
        assert client.patch(f'/api/admin/campaigns/{cid}',headers=admin,json={'status':'LIVE'}).status_code==200
        assert client.post(f'/api/campaigns/{cid}/enroll',headers=referred).status_code==200
        mission=client.get(f'/api/campaigns/{cid}').json()['missions'][0]
        assert client.post(f"/api/campaigns/{cid}/missions/{mission['id']}/complete",headers=referred,json={'answer':None}).status_code==200

        final=client.get('/api/referrals/me',headers=referrer);assert final.status_code==200
        assert final.json()['completed_campaign_conversions']>=1
        assert earnings_for(final.json(),'REF10')==before_reward+5
        assert final.json()['rule'].startswith('Referral rewards come from')
