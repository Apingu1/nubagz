from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.risk_models import DeviceInstallObservation, UserTrustProfile


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_anti_sybil_signals_privacy_and_restriction_enforcement():
    with TestClient(app) as client:
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        a=client.post('/api/auth/register',json={'email':'risk-a@example.com','username':'RiskAUser','password':'RiskPass123!'})
        b=client.post('/api/auth/register',json={'email':'risk-b@example.com','username':'RiskBUser','password':'RiskPass123!'})
        assert a.status_code==200 and b.status_code==200
        ah={'Authorization':f"Bearer {a.json()['access_token']}"};bh={'Authorization':f"Bearer {b.json()['access_token']}"}

        install_id='nubagz-local-install-1234567890'
        assert client.post('/api/risk/context',headers=ah,json={'install_id':install_id}).status_code==200
        assert client.post('/api/risk/context',headers=bh,json={'install_id':install_id}).status_code==200
        db=SessionLocal()
        try:
            rows=db.query(DeviceInstallObservation).all()
            assert rows
            assert all(row.install_hash != install_id for row in rows)
            assert all(len(row.install_hash)==64 for row in rows)
        finally:
            db.close()

        address='0x9999999999999999999999999999999999999999'
        assert client.post('/api/users/payout-addresses',headers=ah,json={'address':address,'chain':'Avalanche','label':'Wallet A','make_primary':True}).status_code==200
        assert client.post('/api/users/payout-addresses',headers=bh,json={'address':address,'chain':'Avalanche','label':'Wallet B','make_primary':True}).status_code==200
        risk=client.post('/api/risk/evaluate',headers=bh)
        assert risk.status_code==200
        data=risk.json()
        assert data['risk_score']>=60
        assert data['risk_band']=='HIGH'
        assert data['trust_level']=='REVIEW'
        assert data['can_earn'] is True
        assert any(s['type']=='SHARED_PAYOUT_ADDRESS' for s in data['signals'])
        assert any(s['type']=='SHARED_DEVICE_INSTALL' for s in data['signals'])
        assert 'cross-site' in data['privacy_note']

        # Give this test its own fully funded live Bag so it does not depend on
        # capacity or reward inventory consumed by earlier tests.
        project=client.post('/api/projects',headers=creator,json={
            'name':'Risk Isolation Project','symbol':'RISKISO',
            'description':'Isolated project used only to verify anti-Sybil enforcement on earning routes.',
            'chain':'Avalanche'
        })
        assert project.status_code==200 and project.json()['status']=='LIVE'
        project_id=project.json()['id']
        bag=client.post('/api/campaigns',headers=creator,json={
            'project_id':project_id,'title':'Risk Isolation Bag',
            'description':'Fresh funded Bag used to test risk enforcement without relying on shared test fixtures.',
            'category':'LEARN','difficulty':'EASY','reward_asset':'RISKISO','funding_type':'TOKEN',
            'token_allocation':10,'gross_reward_per_user':1,'user_share_pct':80,'nubagz_share_pct':15,
            'referral_share_pct':5,'max_users':10,
            'missions':[{'title':'Risk route check','description':'Simple isolated work item for risk-route enrollment testing.','mission_type':'LEARN','verification_type':'SELF_ATTEST','xp_reward':1}]
        })
        assert bag.status_code==200 and bag.json()['status']=='DRAFT'
        target_id=bag.json()['id']
        assert client.post(f'/api/funding/campaigns/{target_id}/declare',headers=creator,json={'amount':10,'tx_hash':'risk-isolation-funding'}).status_code==200
        assert client.post(f'/api/funding/campaigns/{target_id}/verify',headers=admin,json={'amount':10,'tx_hash':'risk-isolation-funding'}).status_code==200
        assert client.post(f'/api/campaigns/{target_id}/publish',headers=creator).status_code==200

        # Earning routes perform their own fresh risk evaluation instead of trusting stale profile state.
        auto=client.post('/api/auth/register',json={'email':'risk-auto@example.com','username':'RiskAutoUser','password':'RiskPass123!'})
        assert auto.status_code==200
        autoh={'Authorization':f"Bearer {auto.json()['access_token']}"}
        enrolled=client.post(f"/api/campaigns/{target_id}/enroll",headers=autoh)
        assert enrolled.status_code==200
        db=SessionLocal()
        try:
            profile=db.query(UserTrustProfile).filter(UserTrustProfile.user_id==auto.json()['user']['id']).first()
            assert profile is not None and profile.last_evaluated_at is not None
        finally:
            db.close()

        restricted=client.post(f"/api/risk/users/{b.json()['user']['id']}/trust",headers=admin,json={'trust_level':'RESTRICTED','note':'Shared payout and local install signal require manual verification.'})
        assert restricted.status_code==200 and restricted.json()['can_earn'] is False
        queue=client.get('/api/risk/users',headers=admin)
        assert queue.status_code==200
        reviewed=next(row for row in queue.json() if row['user_id']==b.json()['user']['id'])
        assert reviewed['latest_review']['trust_level']=='RESTRICTED'
        assert 'manual verification' in reviewed['latest_review']['note']

        overview=client.get('/api/admin/overview',headers=admin)
        assert overview.status_code==200 and overview.json()['open_flags']>=2

        blocked=client.post(f"/api/campaigns/{target_id}/enroll",headers=bh)
        assert blocked.status_code==403 and 'restricted' in blocked.json()['detail'].lower()
        daily=client.get('/api/daily/earn',headers=bh)
        assert daily.status_code==200 and daily.json()['restricted'] is True and daily.json()['opportunity_count']==0

        drop=client.post('/api/bagdrops',headers=creator,json={'project_id':project_id,'title':'Risk Gated Drop','rarity':'COMMON','max_claims':2,'min_bag_score':0,'funding_tx_hash':'risk-drop-funding','items':[{'asset':'RISK','amount_per_claim':1,'funded_amount':2}]})
        assert drop.status_code==200
        assert client.post(f"/api/bagdrops/{drop.json()['id']}/activate",headers=admin).status_code==200
        blocked_drop=client.post(f"/api/bagdrops/{drop.json()['id']}/claim",headers=bh)
        assert blocked_drop.status_code==403 and 'restricted' in blocked_drop.json()['detail'].lower()
