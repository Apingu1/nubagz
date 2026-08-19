from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_campaign_templates_reuse_structure_without_bypassing_funding_or_activation():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        templates=client.get('/api/templates',headers=creator);assert templates.status_code==200
        systems=[t for t in templates.json() if t['is_system']]
        assert len(systems)>=2
        template=systems[0]
        project=next(p for p in client.get('/api/projects/mine',headers=creator).json() if p['status']=='APPROVED')

        under=client.post(f"/api/templates/{template['id']}/instantiate",headers=creator,json={'project_id':project['id'],'title':'Underfunded Template Bag','reward_asset':'TMP17','token_allocation':99,'gross_reward_per_user':10,'max_users':10})
        assert under.status_code==400 and 'maximum gross reward obligation' in under.json()['detail']

        created=client.post(f"/api/templates/{template['id']}/instantiate",headers=creator,json={'project_id':project['id'],'title':'Feature Seventeen Template Bag','reward_asset':'TMP17','token_allocation':100,'gross_reward_per_user':10,'max_users':10})
        assert created.status_code==200
        out=created.json();cid=out['id']
        assert out['status']=='PENDING' and out['funding_status']=='UNFUNDED'
        assert out['missions_created']==len(template['missions'])
        blocked=client.patch(f'/api/admin/campaigns/{cid}',headers=admin,json={'status':'LIVE'})
        assert blocked.status_code==400 and 'funding' in blocked.json()['detail'].lower()

        custom=client.post('/api/templates/from-campaign',headers=creator,json={'campaign_id':cid,'name':'Feature17 reusable','description':'A creator-owned reusable template copied from the pending campaign structure.'})
        assert custom.status_code==200 and custom.json()['is_system'] is False
        listing=client.get('/api/templates',headers=creator).json()
        assert any(t['id']==custom.json()['id'] and t['name']=='Feature17 reusable' for t in listing)
