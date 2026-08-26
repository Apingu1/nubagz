from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_campaign_templates_reuse_unified_challenges_without_bypassing_funding_or_onchain_rules():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        templates=client.get('/api/templates',headers=creator);assert templates.status_code==200
        systems=[t for t in templates.json() if t['is_system']]
        assert len(systems)>=2
        template=systems[0]
        assert template['challenges'] and all('category' in item for item in template['challenges'])
        assert all(item['verification_type']!='SELF_ATTEST' for item in template['challenges'])
        project=next(p for p in client.get('/api/projects/mine',headers=creator).json() if p['status'] in {'LIVE','APPROVED'})

        under=client.post(f"/api/templates/{template['id']}/instantiate",headers=creator,json={'project_id':project['id'],'title':'Underfunded Template Bag','reward_asset':'TMP17','token_allocation':99,'gross_reward_per_user':10,'max_users':10})
        assert under.status_code==400 and 'maximum gross reward obligation' in under.json()['detail']

        created=client.post(f"/api/templates/{template['id']}/instantiate",headers=creator,json={'project_id':project['id'],'title':'Feature Seventeen Template Bag','reward_asset':'TMP17','token_allocation':100,'gross_reward_per_user':10,'max_users':10})
        assert created.status_code==200
        out=created.json();cid=out['id']
        assert out['status']=='DRAFT' and out['funding_status']=='UNFUNDED'
        assert out['challenges_created']==len(template['challenges']) and out['missions_created']==0
        blocked=client.post(f'/api/campaigns/{cid}/publish',headers=creator)
        assert blocked.status_code==409 and 'funding' in blocked.json()['detail'].lower()

        # Create a reusable source whose on-chain rule is expressed directly as
        # a unified ONCHAIN Challenge instead of the retired Mission-rule table.
        target='0x1111111111111111111111111111111111111111'
        source=client.post('/api/campaigns',headers=creator,json={
            'project_id':project['id'],'title':'Feature Seventeen Onchain Source',
            'description':'A reusable Robinhood Chain template source proving on-chain target rules survive cloning.',
            'category':'LEARN','difficulty':'EASY','reward_asset':'TMP17','funding_type':'TOKEN','token_allocation':100,
            'gross_reward_per_user':10,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':10,
            'missions':[],'challenges':[{'title':'Robinhood interaction','description':'Interact with the configured Robinhood Chain target.','category':'ONCHAIN','verification_type':'AUTO','target_id':target,'config':{'chain':'Robinhood','target_address':target,'calldata':'0x','value_wei':'0'},'xp_reward':25}]
        })
        assert source.status_code==200
        source_id=source.json()['id']

        custom=client.post('/api/templates/from-campaign',headers=creator,json={'campaign_id':source_id,'name':'Feature17 reusable','description':'A creator-owned reusable template copied from unified Challenge structure.'})
        assert custom.status_code==200 and custom.json()['is_system'] is False
        assert custom.json()['onchain_rule_count']==1
        listing=client.get('/api/templates',headers=creator).json()
        saved=next(t for t in listing if t['id']==custom.json()['id'])
        assert saved['name']=='Feature17 reusable' and saved['onchain_rule_count']==1
        assert saved['challenges'][0]['category']=='ONCHAIN'
        assert saved['challenges'][0]['target_id']==target
        assert saved['challenges'][0]['config']['chain']=='Robinhood'

        # Instantiating preserves the unified target/config but never carries
        # verified funding, a legacy Mission rule or live state.
        cloned=client.post(f"/api/templates/{custom.json()['id']}/instantiate",headers=creator,json={'project_id':project['id'],'title':'Feature Seventeen Cloned Bag','reward_asset':'TMP17','token_allocation':100,'gross_reward_per_user':10,'max_users':10})
        assert cloned.status_code==200
        clone=cloned.json();assert clone['status']=='DRAFT' and clone['funding_status']=='UNFUNDED'
        assert clone['challenges_created']==1 and clone['missions_created']==0 and clone['onchain_rules_created']==0
        clone_campaign=client.get(f"/api/campaigns/{clone['id']}").json()
        clone_challenge=clone_campaign['challenges'][0]
        assert clone_challenge['category']=='ONCHAIN'
        assert clone_challenge['target_id']==target
        assert clone_challenge['config']['chain']=='Robinhood'
        assert clone_challenge['config']['target_address']==target
        assert client.post(f"/api/campaigns/{clone['id']}/publish",headers=creator).status_code==409
