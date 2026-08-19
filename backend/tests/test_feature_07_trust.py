from fastapi.testclient import TestClient
from app.main import app


def test_project_trust_scores_are_explainable():
    with TestClient(app) as client:
        rows = client.get('/api/trust/projects')
        assert rows.status_code == 200
        assert rows.json()
        first = rows.json()[0]
        assert 0 <= first['score'] <= 100
        assert set(first['factors']) == {'approval', 'verified_funding', 'completion_quality', 'transparency', 'age'}
        assert 'not an endorsement' in first['disclaimer'].lower()
