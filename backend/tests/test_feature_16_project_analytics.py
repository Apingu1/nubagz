from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def register(client,email,username):
    r=client.post('/api/auth/register',json={'email':email,'username':username,'password':'Analytics123!'});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_project_analytics_reconciles_only_campaign_settlement_economics():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        worker=register(client,'feature16-worker@example.com','Feature16Worker')
        second=register(client,'feature16-second@example.com','Feature16Second')
        project=client.post('/api/projects',headers=creator,json={'name':'Feature Sixteen Analytics','symbol':'ANA16','description':'An isolated project used to reconcile participation analytics against funded reward ledger entries.','chain':'Robinhood'})
        assert project.status_code==200 and project.json()['status']=='LIVE'
        pid=project.json()['id']
        campaign=client.post('/api/campaigns',headers=creator,json={
            'project_id':pid,'title':'Analytics Reconciliation Bag','description':'A funded Challenge Bag used to prove creator analytics reconcile only campaign settlement entries.',
            'category':'LEARN','difficulty':'EASY','reward_asset':'ANA16','funding_type':'TOKEN','token_allocation':200,
            'gross_reward_per_user':100,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':2,
            'missions':[],'challenges':[{'title':'Complete','description':'Complete the analytics proof quiz.','category':'LEARN','verification_type':'QUIZ','config':{'answer':'complete'},'xp_reward':10}]
        })
        assert campaign.status_code==200 and campaign.json()['status']=='DRAFT'
        cid=campaign.json()['id']
        assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':200,'tx_hash':'feature16-funding'}).status_code==200
        assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':200,'tx_hash':'feature16-funding'}).status_code==200
        assert client.post(f'/api/campaigns/{cid}/publish',headers=creator).status_code==200
        assert client.post(f'/api/campaigns/{cid}/enroll',headers=worker).status_code==200
        challenge=client.get(f'/api/campaigns/{cid}').json()['challenges'][0]
        assert client.post(f"/api/challenges/{challenge['id']}/complete",headers=worker,json={'answer':'complete'}).status_code==200

        # A separate fixed distribution may reference the same campaign for attribution,
        # but it must not consume the campaign's verified reward inventory.
        dist=client.post('/api/revenue-share',headers=creator,json={'campaign_id':cid,'title':'Separate contributor distribution','asset_symbol':'ANA16','funded_amount':50,'funding_reference':'feature16-separate-pool'})
        assert dist.status_code==200
        did=dist.json()['id']
        assert client.post(f'/api/revenue-share/{did}/activate',headers=admin,json={'funded_amount':50,'funding_reference':'feature16-verified-pool'}).status_code==200
        executed=client.post(f'/api/revenue-share/{did}/execute',headers=creator)
        assert executed.status_code==200 and float(executed.json()['distributed_amount'])==50

        # The second funded campaign slot is still available despite that separate ledger entry.
        assert client.post(f'/api/campaigns/{cid}/enroll',headers=second).status_code==200
        daily=client.get('/api/daily/earn',headers=second)
        assert daily.status_code==200
        assert any(x['type']=='CAMPAIGN' and x['id']==cid for x in daily.json()['opportunities'])

        analytics=client.get(f'/api/project-analytics/projects/{pid}',headers=creator)
        assert analytics.status_code==200
        p=analytics.json()
        assert p['enrollments']==2 and p['completions']==1 and p['unique_completed_participants']==1
        assert p['completion_rate_pct']=='50.00'
        assert p['all_campaigns_reconciled'] is True
        c=next(x for x in p['campaigns'] if x['campaign_id']==cid)
        assert c['funding_status']=='VERIFIED'
        assert float(c['verified_funding'])==200
        assert float(c['distributed_total'])==100
        assert float(c['remaining_verified_funding'])==100
        assert c['funding_utilization_pct']=='50.00'
        assert float(c['linked_non_campaign_distribution_total'])==50
        assert c['reconciled'] is True
        assert float(c['cost_per_completed_participant'])==100
        assert c['referral_conversions']==0
        assert 'bagbuilder_conversions' not in c
        breakdown={row['entry_type']:float(row['amount']) for row in c['settlement_breakdown']}
        assert breakdown=={'CAMPAIGN_REWARD':80.0,'COMMUNITY_SHARE':5.0,'PLATFORM_SHARE':15.0}
        assert p['distributed_by_asset']==[{'asset':'ANA16','amount':'100.00000000'}]
