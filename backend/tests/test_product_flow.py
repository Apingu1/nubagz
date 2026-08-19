import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_nubagz.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-that-is-longer-than-thirty-two-bytes")

from fastapi.testclient import TestClient
from app.main import app


def auth(client, email, password):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_complete_creator_to_earner_flow():
    Path("test_nubagz.db").unlink(missing_ok=True)
    with TestClient(app) as client:
        creator = auth(client, "creator@demo.nubagz.com", "Creator123!")
        admin = auth(client, "admin@demo.nubagz.com", "Admin123!")
        earner = auth(client, "demo@demo.nubagz.com", "Demo123!")

        project = client.post("/api/projects", headers=creator, json={
            "name": "Test Bag Project", "symbol": "TBAG",
            "description": "A project used by the NuBagz automated product lifecycle test suite.",
            "chain": "Avalanche"
        })
        assert project.status_code == 200
        project_id = project.json()["id"]
        assert client.patch(f"/api/admin/projects/{project_id}", headers=admin, json={"status": "APPROVED"}).status_code == 200

        campaign = client.post("/api/campaigns", headers=creator, json={
            "project_id": project_id,
            "title": "Test Participation Bag",
            "description": "Complete this pathway to validate funded allocation and reward accounting.",
            "category": "LEARN", "difficulty": "EASY", "reward_asset": "TBAG", "funding_type": "TOKEN",
            "token_allocation": 100000, "gross_reward_per_user": 100, "user_share_pct": 80,
            "nubagz_share_pct": 15, "referral_share_pct": 5, "max_users": 1000,
            "missions": [
                {"title": "Learn", "description": "Read briefing", "mission_type": "LEARN", "verification_type": "SELF_ATTEST", "xp_reward": 50},
                {"title": "Verify", "description": "Answer token symbol", "mission_type": "LEARN", "verification_type": "QUIZ", "quiz_question": "Token symbol?", "quiz_options": ["TBAG", "BTC"], "quiz_answer": "TBAG", "xp_reward": 75}
            ]
        })
        assert campaign.status_code == 200
        campaign_id = campaign.json()["id"]
        assert client.patch(f"/api/admin/campaigns/{campaign_id}", headers=admin, json={"status": "LIVE"}).status_code == 200
        assert client.post(f"/api/campaigns/{campaign_id}/enroll", headers=earner).status_code == 200

        missions = client.get(f"/api/campaigns/{campaign_id}").json()["missions"]
        assert client.post(f"/api/campaigns/{campaign_id}/missions/{missions[0]['id']}/complete", headers=earner, json={"answer": None}).status_code == 200
        assert client.post(f"/api/campaigns/{campaign_id}/missions/{missions[1]['id']}/complete", headers=earner, json={"answer": "TBAG"}).status_code == 200

        balances = client.get("/api/users/dashboard", headers=earner).json()["balances"]
        assert any(item["asset_symbol"] == "TBAG" and float(item["amount"]) == 80 for item in balances)
        treasury = client.get("/api/admin/treasury", headers=admin).json()
        assert any(item["asset"] == "TBAG" and float(item["amount"]) == 20 for item in treasury)
