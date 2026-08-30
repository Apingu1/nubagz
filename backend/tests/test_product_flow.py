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
            "estimated_value_gbp": 10,
            "challenges": [
                {"title": "Read briefing", "description": "Read the briefing and submit a short evidence note.", "category": "LEARN", "verification_type": "PROJECT_REVIEW", "xp_reward": 50},
                {"title": "Verify", "description": "Answer the token symbol check.", "category": "LEARN", "verification_type": "QUIZ", "config": {"question": "Token symbol?", "options": ["TBAG", "BTC"], "answer": "TBAG"}, "xp_reward": 75}
            ]
        })
        assert campaign.status_code == 200, campaign.text
        campaign_id = campaign.json()["id"]
        challenges = campaign.json()["challenges"]

        unfunded_live = client.patch(f"/api/admin/campaigns/{campaign_id}", headers=admin, json={"status": "LIVE"})
        assert unfunded_live.status_code == 400
        declared = client.post(f"/api/funding/campaigns/{campaign_id}/declare", headers=creator, json={"amount": 100000, "tx_hash": "0xtestfunding"})
        assert declared.status_code == 200
        verified = client.post(f"/api/funding/campaigns/{campaign_id}/verify", headers=admin, json={"amount": 100000, "tx_hash": "0xtestfunding"})
        assert verified.status_code == 200 and verified.json()["fully_funded"] is True
        assert client.patch(f"/api/admin/campaigns/{campaign_id}", headers=admin, json={"status": "LIVE"}).status_code == 200

        blocked = client.post(f"/api/challenges/{challenges[0]['id']}/complete", headers=earner, json={"evidence": "Read the project briefing."})
        assert blocked.status_code == 400 and "join this bag" in blocked.json()["detail"].lower()
        assert client.post(f"/api/campaigns/{campaign_id}/enroll", headers=earner).status_code == 200

        proof = client.post(f"/api/challenges/{challenges[0]['id']}/complete", headers=earner, json={"evidence": "Read the project briefing and checked the token information."})
        assert proof.status_code == 200 and proof.json()["status"] == "PENDING"
        submissions = client.get("/api/challenges/submissions/project", headers=creator)
        assert submissions.status_code == 200
        submission = next(row for row in submissions.json() if row["challenge_id"] == challenges[0]["id"])
        approved = client.post(f"/api/challenges/completions/{submission['id']}/decision", headers=creator, json={"status": "APPROVED"})
        assert approved.status_code == 200 and approved.json()["completed"] is False

        final = client.post(f"/api/challenges/{challenges[1]['id']}/complete", headers=earner, json={"answer": "TBAG"})
        assert final.status_code == 200 and final.json()["completed"] is True
        assert final.json()["reward_status"] == "PENDING_SETTLEMENT"

        # Phase 2.1 records the approved Project Reward without pretending the
        # blockchain settlement has happened. It must not be withdrawable yet.
        balances = client.get("/api/users/dashboard", headers=earner).json()["balances"]
        assert not any(item["asset_symbol"] == "TBAG" for item in balances)
        treasury = client.get("/api/admin/treasury", headers=admin).json()
        assert any(item["asset"] == "TBAG" and float(item["amount"]) == 20 for item in treasury)

        price = client.post("/api/prices/snapshot", headers=admin, json={"asset": "TBAG", "price_gbp": 0.1, "source": "TEST"})
        assert price.status_code == 200
        earnings = client.get("/api/earnings/summary", headers=earner)
        assert earnings.status_code == 200
        summary = earnings.json()
        pending = next(item for item in summary["pending_settlement"] if item["asset"] == "TBAG")
        assert float(pending["amount"]) == 80.0
        valuation = next(item for item in summary["valuations"] if item["asset"] == "TBAG")
        assert float(valuation["current_value_gbp"]) == 0.0
        assert float(valuation["original_estimated_value_gbp"]) == 8.0

        drop = client.post("/api/bagdrops", headers=creator, json={
            "project_id": project_id, "title": "Test Rare Drop", "rarity": "RARE", "max_claims": 10,
            "min_bag_score": 0, "funding_tx_hash": "0xdropfunding",
            "items": [{"asset": "TBAG", "amount_per_claim": 2, "funded_amount": 20}]
        })
        assert drop.status_code == 200
        drop_id = drop.json()["id"]
        assert client.post(f"/api/bagdrops/{drop_id}/activate", headers=admin).status_code == 200
        live_drops = client.get("/api/bagdrops", headers=earner)
        assert any(item["id"] == drop_id for item in live_drops.json())
        daily = client.get("/api/daily/earn", headers=earner)
        assert daily.status_code == 200 and any(item["type"] == "BAGDROP" and item["id"] == drop_id for item in daily.json()["opportunities"])
        claim = client.post(f"/api/bagdrops/{drop_id}/claim", headers=earner)
        assert claim.status_code == 200
        assert client.post(f"/api/bagdrops/{drop_id}/claim", headers=earner).status_code == 409
        balances = client.get("/api/users/dashboard", headers=earner).json()["balances"]
        assert any(item["asset_symbol"] == "TBAG" and float(item["amount"]) == 2 for item in balances)
