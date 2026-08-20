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


def test_bagbuilder_share_is_paid_from_nubagz_share_not_extra_project_cost():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        builder=login(client,'demo@demo.nubagz.com','Demo123!')
        participant_res=client.post('/api/auth/register',json={'email':'feature11-user@example.com','username':'Feature11User','password':'Builder123!'})
        assert participant_res.status_code==200
        participant={'Authorization':f"Bearer {participant_res.json()['access_token']}"}
        retro_res=client.post('/api/auth/register',json={'email':'feature11-retro@example.com','username':'Feature11Retro','password':'Builder123!'})
        assert retro_res.status_code==200
        retro={'Authorization':f"Bearer {retro_res.json()['access_token']}"}

        project=client.post('/api/projects',headers=creator,json={'name':'Feature Eleven Builders','symbol':'BUILD11','description':'An isolated project used to prove BagBuilder creator marketplace economics.','chain':'Avalanche'})
        assert project.status_code==200
        pid=project.json()['id']
        assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200
        campaign=client.post('/api/campaigns',headers=creator,json={
            'project_id':pid,'title':'Community Guided Bag','description':'A funded campaign whose onboarding route can be improved by a community BagBuilder.',
            'category':'LEARN','difficulty':'EASY','reward_asset':'BUILD11','funding_type':'TOKEN','token_allocation':200,
            'gross_reward_per_user':100,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':2,
            'missions':[{'title':'Complete guided route','description':'Finish the approved community onboarding route.','mission_type':'LEARN','verification_type':'SELF_ATTEST','xp_reward':10}]
        })
        assert campaign.status_code==200
        cid=campaign.json()['id']
        assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':200,'tx_hash':'feature11-funding'}).status_code==200
        assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':200,'tx_hash':'feature11-funding'}).status_code==200
        assert client.patch(f'/api/admin/campaigns/{cid}',headers=admin,json={'status':'LIVE'}).status_code==200

        owner_path=client.post('/api/builders',headers=creator,json={'campaign_id':cid,'title':'Owner rebate path','summary':'The project owner must not redirect NuBagz platform economics back to themselves.','creator_share_pct':5})
        assert owner_path.status_code==400

        pathway=client.post('/api/builders',headers=builder,json={'campaign_id':cid,'title':'Five-minute beginner path','summary':'A plain-language route that explains the project before the user completes the funded campaign.','creator_share_pct':5})
        assert pathway.status_code==200 and pathway.json()['status']=='PENDING'
        pathway_id=pathway.json()['id']
        duplicate=client.post('/api/builders',headers=builder,json={'campaign_id':cid,'title':'Duplicate active path','summary':'A second active pathway for the same builder and campaign must not be allowed.','creator_share_pct':4})
        assert duplicate.status_code==409
        assert client.patch(f'/api/builders/{pathway_id}',headers=creator,json={'status':'APPROVED'}).status_code==200

        assert client.post(f'/api/campaigns/{cid}/enroll',headers=retro).status_code==200
        retro_start=client.post(f'/api/builders/{pathway_id}/start',headers=retro)
        assert retro_start.status_code==409 and 'retroactively' in retro_start.json()['detail'].lower()

        assert client.post(f'/api/builders/{pathway_id}/start',headers=participant).status_code==200
        assert client.post(f'/api/campaigns/{cid}/enroll',headers=participant).status_code==200
        mission=client.get(f'/api/campaigns/{cid}').json()['missions'][0]
        complete=client.post(f"/api/campaigns/{cid}/missions/{mission['id']}/complete",headers=participant,json={'answer':None})
        assert complete.status_code==200 and complete.json()['completed'] is True

        assert asset_balance(client, participant, 'BUILD11')==80
        assert asset_balance(client, builder, 'BUILD11')==5
        assert treasury_balance(client, admin, 'BUILD11')==15

        stats=client.get('/api/builders/stats',headers=builder)
        assert stats.status_code==200
        data=stats.json()
        assert data['total_pathways']>=1
        assert data['approved_pathways']>=1
        assert data['attributed_users']>=1
        assert data['completed_conversions']>=1
        earned=next(row for row in data['earnings'] if row['asset_symbol']=='BUILD11')
        assert float(earned['amount'])>=5

        mine=client.get('/api/builders/mine',headers=builder)
        assert mine.status_code==200
        row=next(x for x in mine.json() if x['id']==pathway_id)
        assert row['attributed_users']==1 and row['completed_conversions']==1
