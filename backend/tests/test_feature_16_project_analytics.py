from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_project_analytics_reconciles_participation_and_ledger_economics():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        worker=client.post('/api/auth/register',json={'email':'feature16-worker@example.com','username':'Feature16Worker','password':'Analytics123!'})
        assert worker.status_code==200
        wh={'Authorization':f"Bearer {worker.json()['access_token']}"}
        project=client.post('/api/projects',headers=creator,json={'name':'Feature Sixteen Analytics','symbol':'ANA16','description':'An isolated project used to reconcile participation analytics against funded reward ledger entries.','chain':'Avalanche'})
        assert project.status_code==200
        pid=project.json()['id']
        assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200
        campaign=client.post('/api/campaigns',headers=creator,json={
            'project_id':pid,'title':'Analytics Reconciliation Bag','description':'A one participant funded campaign used to prove project analytics are ledger backed.',
            'category':'LEARN','difficulty':'EASY','reward_asset':'ANA16','funding_type':'TOKEN','token_allocation':100,
            'gross_reward_per_user':100,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':1,
            'missions':[{'title':'Complete','description':'Complete the analytics proof pathway','mission_type':'LEARN','verification_type':'SELF_ATTEST','xp_reward':10}]
        })
        assert campaign.status_code==200
        cid=campaign.json()['id']
        assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':100,'tx_hash':'feature16-funding'}).status_code==200
        assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':100,'tx_hash':'feature16-funding'}).status_code==200
        assert client.patch(f'/api/admin/campaigns/{cid}',headers=admin,json={'status':'LIVE'}).status_code==200
        assert client.post(f'/api/campaigns/{cid}/enroll',headers=wh).status_code==200
        mission=client.get(f'/api/campaigns/{cid}').json()['missions'][0]
        assert client.post(f"/api/campaigns/{cid}/missions/{mission['id']}/complete",headers=wh,json={'answer':None}).status_code==200

        analytics=client.get(f'/api/project-analytics/projects/{pid}',headers=creator)
        assert analytics.status_code==200
        p=analytics.json()
        assert p['enrollments']==1 and p['completions']==1 and p['unique_completed_participants']==1
        assert p['completion_rate_pct']=='100.00'
        c=next(x for x in p['campaigns'] if x['campaign_id']==cid)
        assert c['funding_status']=='VERIFIED'
        assert float(c['verified_funding'])==100
        assert float(c['distributed_total'])==100
        assert float(c['cost_per_completed_participant'])==100
        assert c['referral_conversions']==0 and c['bagbuilder_conversions']==0
        assert p['distributed_by_asset']==[{'asset':'ANA16','amount':'100.00000000'}]
