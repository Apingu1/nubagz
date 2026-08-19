from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def register(client,email,username):
    r=client.post('/api/auth/register',json={'email':email,'username':username,'password':'Reports123!'});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}

def project_status(client,admin,pid):
    rows=client.get('/api/admin/projects',headers=admin).json()
    return next(p for p in rows if p['id']==pid)['status']


def test_report_is_a_case_not_an_automatic_penalty():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!');admin=login(client,'admin@demo.nubagz.com','Admin123!')
        reporter=register(client,'feature19-reporter@example.com','Feature19Reporter');outsider=register(client,'feature19-outsider@example.com','Feature19Outsider')
        project=client.post('/api/projects',headers=creator,json={'name':'Feature Nineteen Reports','symbol':'RPT19','description':'An isolated project used to prove reports require explicit moderation and due process.','chain':'Avalanche'});assert project.status_code==200
        pid=project.json()['id'];assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200

        opened=client.post('/api/reports',headers=reporter,json={'target_type':'PROJECT','target_id':pid,'category':'SAFETY','detail':'I am reporting a specific project concern that should be reviewed by moderation before any action is taken.'})
        assert opened.status_code==200
        case=opened.json();rid=case['id']
        assert case['status']=='OPEN' and case['resolution_action']=='NONE'
        assert project_status(client,admin,pid)=='APPROVED'

        assert client.get(f'/api/reports/{rid}',headers=outsider).status_code==404
        affected=client.get('/api/reports/affected',headers=creator);assert affected.status_code==200
        found=next(r for r in affected.json() if r['id']==rid)
        assert found['reporter']=='Participant' and found['is_target_owner'] is True
        response=client.post(f'/api/reports/{rid}/messages',headers=creator,json={'message':'Project owner response added for the moderator to consider.'})
        assert response.status_code==200 and len(response.json()['messages'])==1
        assert project_status(client,admin,pid)=='APPROVED'

        resolved=client.post(f'/api/reports/{rid}/resolve',headers=admin,json={'status':'RESOLVED','action':'SUSPEND_PROJECT','note':'Admin reviewed the evidence and explicitly suspended the project.'})
        assert resolved.status_code==200
        assert resolved.json()['status']=='RESOLVED' and resolved.json()['resolution_action']=='SUSPEND_PROJECT'
        assert project_status(client,admin,pid)=='SUSPENDED'
        assert client.post(f'/api/reports/{rid}/messages',headers=creator,json={'message':'Closed cases should reject new dispute messages.'}).status_code==409
