from fastapi.testclient import TestClient
from app.main import app


def login(client,email,password):
    r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200
    return {'Authorization':f"Bearer {r.json()['access_token']}"}


def test_notifications_are_private_deduped_and_read_state_persists():
    with TestClient(app) as client:
        creator=login(client,'creator@demo.nubagz.com','Creator123!')
        admin=login(client,'admin@demo.nubagz.com','Admin123!')
        earner=login(client,'demo@demo.nubagz.com','Demo123!')
        project=client.post('/api/projects',headers=creator,json={'name':'Feature Fifteen Signals','symbol':'NOTE15','description':'An isolated project used to prove private persisted notification behaviour.','chain':'Avalanche'})
        assert project.status_code==200
        pid=project.json()['id']
        assert client.patch(f'/api/admin/projects/{pid}',headers=admin,json={'status':'APPROVED'}).status_code==200

        first=client.get('/api/notifications',headers=creator);assert first.status_code==200
        matches=[n for n in first.json()['notifications'] if 'Feature Fifteen Signals' in n['title']]
        assert len(matches)==1 and matches[0]['read'] is False
        notice_id=matches[0]['id']
        count=first.json()['total_count']
        assert count==len(first.json()['notifications'])
        assert first.json()['unread_count']>=1

        again=client.get('/api/notifications',headers=creator);assert again.status_code==200
        assert again.json()['total_count']==count
        assert len([n for n in again.json()['notifications'] if n['id']==notice_id])==1

        other=client.get('/api/notifications',headers=earner);assert other.status_code==200
        assert all(n['id']!=notice_id for n in other.json()['notifications'])
        assert client.post(f'/api/notifications/{notice_id}/read',headers=earner).status_code==404

        marked=client.post(f'/api/notifications/{notice_id}/read',headers=creator);assert marked.status_code==200
        assert marked.json()['read'] is True and marked.json()['read_at']
        persisted=client.get('/api/notifications',headers=creator).json()
        assert next(n for n in persisted['notifications'] if n['id']==notice_id)['read'] is True

        read_all=client.post('/api/notifications/read-all',headers=creator);assert read_all.status_code==200
        after_all=client.get('/api/notifications',headers=creator).json()
        assert after_all['unread_count']==0
        assert all(n['read'] is True for n in after_all['notifications'])
        repeated=client.post('/api/notifications/read-all',headers=creator);assert repeated.status_code==200
        assert repeated.json()['marked_read']==0
