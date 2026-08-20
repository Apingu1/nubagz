from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def balance(client, headers, asset):
    rows=client.get('/api/users/dashboard',headers=headers).json()['balances']
    return sum(float(r['amount']) for r in rows if r['asset_symbol']==asset)


def test_bounty_requires_full_funding_and_pays_only_approved_unique_submission():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        worker_res=client.post('/api/auth/register',json={'email':'feature12-worker@example.com','username':'Feature12Worker','password':'Bounty123!'})
        assert worker_res.status_code==200
        worker={'Authorization':f"Bearer {worker_res.json()['access_token']}"}

        project=client.post('/api/projects',headers=creator,json={'name':'Feature Twelve Bounties','symbol':'BNTY12','description':'An isolated project used to prove fully funded bounty reward accounting.','chain':'Avalanche'})
        assert project.status_code==200
        pid=project.json()['id']
        assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200

        underfunded=client.post('/api/bounties',headers=creator,json={'project_id':pid,'title':'Underfunded bounty','description':'This intentionally underfunded bounty must be rejected before it can exist.','reward_asset':'BNTY12','reward_per_winner':25,'max_winners':2,'funded_amount':49,'funding_reference':'feature12-under'})
        assert underfunded.status_code==400

        bounty=client.post('/api/bounties',headers=creator,json={'project_id':pid,'title':'Write a useful project explainer','description':'Produce a concise beginner-friendly explainer and submit the finished work for project review.','reward_asset':'BNTY12','reward_per_winner':25,'max_winners':2,'funded_amount':50,'funding_reference':'feature12-declared'})
        assert bounty.status_code==200 and bounty.json()['status']=='PENDING'
        assert bounty.json()['funding_status']=='DECLARED'
        bid=bounty.json()['id']

        insufficient_verify=client.post(f'/api/bounties/{bid}/activate',headers=admin,json={'funded_amount':49,'funding_reference':'feature12-chain-proof'})
        assert insufficient_verify.status_code==400
        verified=client.post(f'/api/bounties/{bid}/activate',headers=admin,json={'funded_amount':50,'funding_reference':'feature12-chain-proof'})
        assert verified.status_code==200
        assert verified.json()['status']=='LIVE' and verified.json()['funding_status']=='VERIFIED'
        assert verified.json()['funding_reference']=='feature12-chain-proof'
        assert client.post(f'/api/bounties/{bid}/activate',headers=admin,json={'funded_amount':50,'funding_reference':'feature12-chain-proof'}).status_code==409

        owner_submit=client.post(f'/api/bounties/{bid}/submit',headers=creator,json={'evidence':'https://example.com/project-owner-proof'})
        assert owner_submit.status_code==400

        submission=client.post(f'/api/bounties/{bid}/submit',headers=worker,json={'evidence':'https://example.com/feature12-proof'})
        assert submission.status_code==200
        sid=submission.json()['id']
        assert client.post(f'/api/bounties/{bid}/submit',headers=worker,json={'evidence':'duplicate attempt'}).status_code==409
        approved=client.post(f'/api/bounties/submissions/{sid}/decision',headers=creator,json={'status':'APPROVED'})
        assert approved.status_code==200 and approved.json()['status']=='APPROVED'
        assert approved.json()['reviewed_at'] is not None
        assert balance(client,worker,'BNTY12')==25
        assert client.post(f'/api/bounties/submissions/{sid}/decision',headers=creator,json={'status':'APPROVED'}).status_code==409

        history=client.get('/api/bounties/submissions/mine',headers=worker)
        assert history.status_code==200
        mine=next(x for x in history.json() if x['id']==sid)
        assert mine['status']=='APPROVED'

        live=client.get('/api/bounties',headers=worker)
        assert live.status_code==200
        row=next(x for x in live.json() if x['id']==bid)
        assert row['winners_count']==1 and row['remaining_winners']==1 and float(row['distributed_amount'])==25
        assert float(row['remaining_funded_amount'])==25
        assert 'funding_reference' not in row

        admin_rows=client.get('/api/bounties/admin',headers=admin)
        admin_row=next(x for x in admin_rows.json() if x['id']==bid)
        assert admin_row['funding_reference']=='feature12-chain-proof'
