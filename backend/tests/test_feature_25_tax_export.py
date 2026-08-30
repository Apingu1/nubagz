from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import LedgerEntry


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def register(client,email,username):
    r=client.post('/api/auth/register',json={'email':email,'username':username,'password':'TaxExport123!'});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"},r.json()['user']['id']


def test_yearly_earnings_statement_and_csv_include_estimated_receipts_and_withdrawal_destination():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!');admin=login(client,'admin@demo.nubagz.com','Admin123!')
        worker,worker_id=register(client,'feature25-worker@example.com','Feature25Worker');outsider,_=register(client,'feature25-outsider@example.com','Feature25Outsider')
        project=client.post('/api/projects',headers=creator,json={'name':'Feature Twenty Five Export','symbol':'TAX25','description':'An isolated Robinhood project used to prove yearly earnings export includes only authenticated user activity.','chain':'Robinhood'});assert project.status_code==200
        pid=project.json()['id'];assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200
        campaign=client.post('/api/campaigns',headers=creator,json={
            'project_id':pid,'title':'Tax Export Bag','description':'A funded Challenge Bag with a recorded GBP estimate used for the yearly earnings statement.',
            'category':'LEARN','difficulty':'EASY','reward_asset':'TAX25','funding_type':'TOKEN','token_allocation':10,
            'gross_reward_per_user':10,'user_share_pct':80,'nubagz_share_pct':15,'referral_share_pct':5,'max_users':1,'estimated_value_gbp':5,
            'missions':[],'challenges':[{'title':'Complete','description':'Complete the yearly export proof quiz.','category':'LEARN','verification_type':'QUIZ','config':{'answer':'complete'},'xp_reward':10}]
        });assert campaign.status_code==200
        cid=campaign.json()['id'];assert client.post(f'/api/funding/campaigns/{cid}/declare',headers=creator,json={'amount':10,'tx_hash':'feature25-funding'}).status_code==200;assert client.post(f'/api/funding/campaigns/{cid}/verify',headers=admin,json={'amount':10,'tx_hash':'feature25-funding'}).status_code==200;assert client.patch(f'/api/admin/campaigns/{cid}',headers=admin,json={'status':'LIVE'}).status_code==200
        assert client.post(f'/api/campaigns/{cid}/enroll',headers=worker).status_code==200
        challenge=client.get(f'/api/campaigns/{cid}').json()['challenges'][0]
        complete=client.post(f"/api/challenges/{challenge['id']}/complete",headers=worker,json={'answer':'complete'})
        assert complete.status_code==200 and complete.json()['reward_status']=='PENDING_SETTLEMENT'

        destination='0x2222222222222222222222222222222222222222'
        payout=client.post('/api/users/payout-addresses',headers=worker,json={'address':destination,'chain':'Robinhood','label':'Tax export destination','make_primary':True})
        assert payout.status_code==200

        # The approved Project Reward is not withdrawable before settlement.
        blocked=client.post('/api/users/withdrawals',headers=worker,json={'asset_symbol':'TAX25','amount':1,'chain':'Robinhood','wallet_address':destination})
        assert blocked.status_code==400

        # Keep withdrawal-history/export coverage using a separate genuinely AVAILABLE
        # reward type; Phase 2.1 does not redesign unrelated available ledger entries.
        with SessionLocal() as db:
            db.add(LedgerEntry(user_id=worker_id,asset_symbol='TAX25',amount=1,entry_type='TEST_AVAILABLE_REWARD',status='AVAILABLE',note='CI available reward for withdrawal export'))
            db.commit()
        withdrawal=client.post('/api/users/withdrawals',headers=worker,json={'asset_symbol':'TAX25','amount':1,'chain':'Robinhood','wallet_address':destination})
        assert withdrawal.status_code==200

        report=client.get('/api/earnings/tax-report?year=2026',headers=worker);assert report.status_code==200
        body=report.json();assert body['year']==2026 and body['basis']=='CALENDAR_YEAR'
        receipt=next(r for r in body['receipts'] if r['entry_type']=='CAMPAIGN_REWARD' and r['asset']=='TAX25')
        assert float(receipt['amount'])==8 and receipt['status']=='PENDING_SETTLEMENT' and receipt['estimated_value_gbp']=='4.00' and receipt['valuation_source']=='CAMPAIGN_ESTIMATE'
        wd=next(w for w in body['withdrawals'] if w['asset']=='TAX25')
        assert wd['wallet_address']==destination and wd['status']=='PENDING'
        assert wd['chain']=='Robinhood'
        assert 'not tax advice' in body['disclaimer'].lower() and body['unpriced_withdrawal_count']>=1

        csv_res=client.get('/api/earnings/tax-export.csv?year=2026',headers=worker);assert csv_res.status_code==200
        assert csv_res.headers['content-type'].startswith('text/csv') and 'nubagz-earnings-2026.csv' in csv_res.headers.get('content-disposition','')
        text=csv_res.text
        assert 'CAMPAIGN_REWARD' in text and 'PENDING_SETTLEMENT' in text and destination in text and 'TAX25' in text and 'Robinhood' in text

        other=client.get('/api/earnings/tax-report?year=2026',headers=outsider);assert other.status_code==200
        assert all(w['wallet_address']!=destination for w in other.json()['withdrawals'])
        assert all(r['campaign_id']!=cid for r in other.json()['receipts'])
