import json
import time
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.db import SessionLocal
from app.models import User
from app.challenge_models import SocialAccount
from app.routers import challenges as challenges_router


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_privy_social_identity_exchange_is_stable_and_verified():
    private_key=ec.generate_private_key(ec.SECP256R1())
    public_pem=private_key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    old_app_id,old_key=settings.privy_app_id,settings.privy_verification_key
    settings.privy_app_id='feature26-privy-app';settings.privy_verification_key=public_pem
    now=int(time.time())
    token=jwt.encode({
        'sub':'did:privy:feature26-google-user','iss':'privy.io','aud':'feature26-privy-app','iat':now,'exp':now+3600,
        'linked_accounts':json.dumps([{'type':'google_oauth','subject':'google-feature26-001','email':'feature26-google@example.com','name':'Feature Twenty Six'}]),
    },private_key,algorithm='ES256')
    try:
        with TestClient(app) as client:
            first=client.post('/api/auth/privy',json={'identity_token':token})
            assert first.status_code==200,first.text
            second=client.post('/api/auth/privy',json={'identity_token':token})
            assert second.status_code==200
            assert second.json()['user']['id']==first.json()['user']['id']
            headers={'Authorization':f"Bearer {first.json()['access_token']}"}
            rows=client.get('/api/auth/social-accounts',headers=headers)
            assert rows.status_code==200
            assert len(rows.json())==1 and rows.json()[0]['provider']=='GOOGLE'
            assert rows.json()[0]['provider_user_id']=='google-feature26-001'
    finally:
        settings.privy_app_id=old_app_id;settings.privy_verification_key=old_key


def test_unified_bag_work_verifies_x_and_settles_once():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        worker_res=client.post('/api/auth/register',json={'email':'feature26-worker@example.com','username':'Feature26Worker','password':'BagWork123!'})
        assert worker_res.status_code==200
        worker={'Authorization':f"Bearer {worker_res.json()['access_token']}"}
        worker_id=worker_res.json()['user']['id']

        project=client.post('/api/projects',headers=creator,json={'name':'Feature Twenty Six Work','symbol':'BW26','description':'A project used to prove the unified Bag Work and X verification architecture.','chain':'Avalanche'})
        assert project.status_code==200
        pid=project.json()['id']
        assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200

        campaign=client.post('/api/campaigns',headers=creator,json={
            'project_id':pid,'title':'Unified Bag Work test','description':'One funded Bag containing social and ordinary work in the same challenge model.',
            'category':'DISCOVER','difficulty':'EASY','reward_asset':'BW26','funding_type':'TOKEN','token_allocation':20,'gross_reward_per_user':20,
            'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':1,
            'challenges':[
                {'title':'Repost the launch','description':'Repost the official launch post on X.','category':'SOCIAL','provider':'X','action':'REPOST','verification_type':'AUTO','target_url':'https://x.com/nubagz/status/123456789','xp_reward':25},
                {'title':'Read the project brief','description':'Read the short project brief and mark it complete.','category':'BAG_WORK','verification_type':'SELF_ATTEST','xp_reward':25},
            ],
        })
        assert campaign.status_code==200,campaign.text
        cid=campaign.json()['id']
        assert len(campaign.json()['challenges'])==2
        assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':20,'tx_hash':'0xfeature26fund'}).status_code==200
        assert client.patch(f'/api/admin/campaigns/{cid}',headers=admin,json={'status':'LIVE'}).status_code==200

        db=SessionLocal()
        try:
            db.add(SocialAccount(user_id=worker_id,provider='X',provider_user_id='260026',privy_user_id='did:privy:feature26-x',username='feature26worker'))
            db.commit()
        finally: db.close()

        feed=client.get('/api/challenges',headers=worker)
        assert feed.status_code==200
        items=[r for r in feed.json() if r['campaign_id']==cid]
        assert len(items)==2
        social=next(r for r in items if r['category']=='SOCIAL')
        ordinary=next(r for r in items if r['category']=='BAG_WORK')

        original=challenges_router.verify_x_action
        challenges_router.verify_x_action=lambda account,challenge:(True,{'source':'TEST_X','x_user_id':account.provider_user_id,'action':challenge.action})
        try:
            verified=client.post(f"/api/challenges/{social['id']}/complete",headers=worker,json={})
            assert verified.status_code==200,verified.text
            assert verified.json()['status']=='VERIFIED' and verified.json()['completed'] is False
            duplicate=client.post(f"/api/challenges/{social['id']}/complete",headers=worker,json={})
            assert duplicate.status_code==409
            final=client.post(f"/api/challenges/{ordinary['id']}/complete",headers=worker,json={})
            assert final.status_code==200,final.text
            assert final.json()['completed'] is True
        finally:
            challenges_router.verify_x_action=original

        balances=client.get('/api/users/dashboard',headers=worker).json()['balances']
        amount=sum(float(row['amount']) for row in balances if row['asset_symbol']=='BW26')
        assert amount==16
        refreshed=client.get('/api/challenges',headers=worker).json()
        statuses={r['id']:r['completion_status'] for r in refreshed if r['campaign_id']==cid}
        assert statuses[social['id']]=='VERIFIED' and statuses[ordinary['id']]=='VERIFIED'
