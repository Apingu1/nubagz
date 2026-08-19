from fastapi.testclient import TestClient
from app.main import app

def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def test_referral_dashboard_counts_referred_registration():
    with TestClient(app) as client:
        referrer=login(client,'demo@demo.nubagz.com','Demo123!')
        before=client.get('/api/referrals/me',headers=referrer);assert before.status_code==200
        code=before.json()['referral_code'];count=before.json()['referred_users']
        created=client.post('/api/auth/register',json={'email':'feature10-ref@example.com','username':'Feature10Ref','password':'Referral123!','referral_code':code})
        assert created.status_code==200
        after=client.get('/api/referrals/me',headers=referrer);assert after.status_code==200
        assert after.json()['referred_users']==count+1
        assert after.json()['rule'].startswith('Referral rewards come from')
