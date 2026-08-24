from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_campaign_templates_reuse_structure_without_bypassing_funding_publish_or_onchain_rules():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        templates=client.get('/api/templates',headers=creator);assert templates.status_code==200
        systems=[t for t in templates.json() if t['is_system']]
        assert len(systems)>=2
        template=systems[0]
        project=next(p for p in client.get('/api/projects/mine',headers=creator).json() if p['status'] in {'LIVE','APPROVED'})

        under=client.post(f"/api/templates/{template['id']}/instantiate",headers=creator,json={'project_id':project['id'],'title':'Underfunded Template Bag','reward_asset':'TMP17','token_allocation':99,'gross_reward_per_user':10,'max_users':10})
        assert under.status_code==400 and 'maximum gross reward obligation' in under.json()['detail']

        created=client.post(f"/api/templates/{template['id']}/instantiate",headers=creator,json={'project_id':project['id'],'title':'Feature Seventeen Template Bag','reward_asset':'TMP17','token_allocation':100,'gross_reward_per_user':10,'max_users':10})
        assert created.status_code==200
        out=created.json();cid=out['id']
        assert out['status']=='DRAFT' and out['funding_status']=='UNFUNDED'
        assert out['missions_created']==len(template['missions']) and out['onchain_rules_created']==0
        blocked=client.post(f'/api/campaigns/{cid}/publish',headers=creator)
        assert blocked.status_code==400 and 'funding' in blocked.json()['detail'].lower()

        # Add a stronger verification rule to the source campaign before saving it.
        source_mission=client.get(f'/api/campaigns/{cid}').json()['missions'][0]
        rule=client.post('/api/onchain/rules',headers=creator,json={'mission_id':source_mission['id'],'chain':'Avalanche','rule_type':'CONTRACT_INTERACTION','contract_address':'0x1111111111111111111111111111111111111111','token_decimals':18})
        assert rule.status_code==200

        custom=client.post('/api/templates/from-campaign',headers=creator,json={'campaign_id':cid,'name':'Feature17 reusable','description':'A creator-owned reusable template copied from the draft campaign structure.'})
        assert custom.status_code==200 and custom.json()['is_system'] is False
        assert custom.json()['onchain_rule_count']==1
        listing=client.get('/api/templates',headers=creator).json()
        saved=next(t for t in listing if t['id']==custom.json()['id'])
        assert saved['name']=='Feature17 reusable' and saved['onchain_rule_count']==1
        assert saved['missions'][0]['onchain_rule']['rule_type']=='CONTRACT_INTERACTION'

        # Instantiating the creator template preserves the rule but never carries verified funding or live state.
        cloned=client.post(f"/api/templates/{custom.json()['id']}/instantiate",headers=creator,json={'project_id':project['id'],'title':'Feature Seventeen Cloned Bag','reward_asset':'TMP17','token_allocation':100,'gross_reward_per_user':10,'max_users':10})
        assert cloned.status_code==200
        clone=cloned.json();assert clone['status']=='DRAFT' and clone['funding_status']=='UNFUNDED' and clone['onchain_rules_created']==1
        clone_campaign=client.get(f"/api/campaigns/{clone['id']}").json()
        clone_mission=clone_campaign['missions'][0]
        mine=client.get('/api/onchain/mine',headers=creator);assert mine.status_code==200
        cloned_rule=next(r for r in mine.json() if r['mission_id']==clone_mission['id'])
        assert cloned_rule['rule_type']=='CONTRACT_INTERACTION'
        assert cloned_rule['contract_address']=='0x1111111111111111111111111111111111111111'
        assert client.post(f"/api/campaigns/{clone['id']}/publish",headers=creator).status_code==400
