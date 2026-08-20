from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def earnings_for(payload, asset):
    return sum(float(row['amount']) for row in payload['earnings'] if row['asset']==asset)


def complete_one_step(client, headers, campaign_id):
    assert client.post(f'/api/campaigns/{campaign_id}/enroll',headers=headers).status_code==200
    mission=client.get(f'/api/campaigns/{campaign_id}').json()['missions'][0]
    result=client.post(f"/api/campaigns/{campaign_id}/missions/{mission['id']}/complete",headers=headers,json={'answer':None})
    assert result.status_code==200 and result.json()['completed'] is True


def test_referrals_pay_only_for_funded_conversions_and_reviewed_rewards_redirect():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        referrer_signup=client.post('/api/auth/register',json={'email':'feature10-referrer@example.com','username':'Feature10Referrer','password':'Referral123!'})
        assert referrer_signup.status_code==200
        referrer={'Authorization':f"Bearer {referrer_signup.json()['access_token']}"}
        referrer_id=referrer_signup.json()['user']['id']
        clean=client.post('/api/risk/evaluate',headers=referrer)
        assert clean.status_code==200 and clean.json()['trust_level']=='NORMAL' and clean.json()['risk_score']<30

        invalid=client.post('/api/auth/register',json={'email':'feature10-invalid@example.com','username':'Feature10Invalid','password':'Referral123!','referral_code':'NOTAREALCODE'})
        assert invalid.status_code==400 and 'Referral code' in invalid.json()['detail']

        before=client.get('/api/referrals/me',headers=referrer);assert before.status_code==200
        assert before.json()['reward_eligible'] is True and before.json()['trust_level']=='NORMAL'
        code=before.json()['referral_code'];count=before.json()['referred_users'];before_reward=earnings_for(before.json(),'REF10')
        validated=client.get(f'/api/referrals/validate/{code}')
        assert validated.status_code==200 and validated.json()['valid'] is True and validated.json()['eligible'] is True

        first=client.post('/api/auth/register',json={'email':'feature10-ref-a@example.com','username':'Feature10RefA','password':'Referral123!','referral_code':code})
        second=client.post('/api/auth/register',json={'email':'feature10-ref-b@example.com','username':'Feature10RefB','password':'Referral123!','referral_code':code})
        assert first.status_code==200 and second.status_code==200
        first_h={'Authorization':f"Bearer {first.json()['access_token']}"};second_h={'Authorization':f"Bearer {second.json()['access_token']}"}
        after_signup=client.get('/api/referrals/me',headers=referrer)
        assert after_signup.json()['referred_users']==count+2
        assert earnings_for(after_signup.json(),'REF10')==before_reward
        assert after_signup.json()['pending_users']>=2

        project=client.post('/api/projects',headers=creator,json={'name':'Feature Ten Referrals','symbol':'REF10','description':'An isolated funded project used to prove performance based referral economics.','chain':'Avalanche'})
        assert project.status_code==200
        pid=project.json()['id']
        assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200
        campaign=client.post('/api/campaigns',headers=creator,json={
            'project_id':pid,'title':'Referral Conversion Bag','description':'A funded one-step Bag used to validate referral economics after real participation.',
            'category':'LEARN','difficulty':'EASY','reward_asset':'REF10','funding_type':'TOKEN','token_allocation':200,
            'gross_reward_per_user':100,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':2,
            'missions':[{'title':'Participate','description':'Complete the funded referral pathway','mission_type':'LEARN','verification_type':'SELF_ATTEST','xp_reward':10}]
        })
        assert campaign.status_code==200
        cid=campaign.json()['id']
        assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':200,'tx_hash':'feature10-funding'}).status_code==200
        assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':200,'tx_hash':'feature10-funding'}).status_code==200
        assert client.patch(f'/api/admin/campaigns/{cid}',headers=admin,json={'status':'LIVE'}).status_code==200

        complete_one_step(client,first_h,cid)
        paid=client.get('/api/referrals/me',headers=referrer).json()
        assert paid['reward_eligible'] is True
        assert earnings_for(paid,'REF10')==before_reward+5
        assert paid['completed_campaign_conversions']>=1
        assert any(e['status']=='PAID' and e['referred_username']=='Feature10RefA' and float(e['paid_amount'])==5 for e in paid['events'])

        reviewed=client.post(f'/api/risk/users/{referrer_id}/trust',headers=admin,json={'trust_level':'REVIEW','note':'Feature 10 referral payout review test'})
        assert reviewed.status_code==200
        validation=client.get(f'/api/referrals/validate/{code}').json()
        assert validation['valid'] is True and validation['eligible'] is False and validation['trust_level']=='REVIEW'
        paused=client.get('/api/referrals/me',headers=referrer).json()
        assert paused['reward_eligible'] is False and paused['trust_level']=='REVIEW'
        blocked_signup=client.post('/api/auth/register',json={'email':'feature10-blocked@example.com','username':'Feature10Blocked','password':'Referral123!','referral_code':code})
        assert blocked_signup.status_code==400

        complete_one_step(client,second_h,cid)
        final=client.get('/api/referrals/me',headers=referrer);assert final.status_code==200
        payload=final.json()
        assert earnings_for(payload,'REF10')==before_reward+5
        assert payload['redirected_conversions']>=1
        assert any(e['status']=='REDIRECTED' and e['referred_username']=='Feature10RefB' and float(e['paid_amount'])==0 for e in payload['events'])
        assert payload['rule'].startswith('No reward is paid for a signup')
        assert 'community treasury' in payload['abuse_rule']

        restored=client.post(f'/api/risk/users/{referrer_id}/trust',headers=admin,json={'trust_level':'NORMAL','note':'Feature 10 test cleanup'})
        assert restored.status_code==200
