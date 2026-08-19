from fastapi.testclient import TestClient
from app.main import app


def test_project_trust_scores_are_explainable_and_funding_aware():
    with TestClient(app) as client:
        rows = client.get('/api/trust/projects')
        assert rows.status_code == 200
        assert rows.json()
        for item in rows.json():
            assert 0 <= item['score'] <= 100
            assert set(item['factors']) == {'approval', 'verified_funding', 'completion_quality', 'transparency', 'age'}
            assert item['score'] == min(100, sum(item['factors'].values()))
            assert item['score_version'] == '1.0'
            assert item['calculated_at']
            assert item['metrics']['verified_funded_campaigns'] <= item['metrics']['campaigns']
            if item['metrics']['campaigns']:
                assert item['metrics']['verified_funded_campaigns'] == item['metrics']['campaigns']
            assert 'not an endorsement' in item['disclaimer'].lower()
            single = client.get(f"/api/trust/projects/{item['project_id']}")
            assert single.status_code == 200
            assert single.json()['score'] == item['score']
