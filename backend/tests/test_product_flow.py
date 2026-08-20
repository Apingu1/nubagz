import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_nubagz.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-that-is-longer-than-thirty-two-bytes")

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from app.main import app
from app.routers import onchain as onchain_router


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

        account = Account.create()
        challenge = client.post("/api/users/wallets/challenge", headers=earner, json={"address": account.address})
        assert challenge.status_code == 200
        signed = Account.sign_message(encode_defunct(text=challenge.json()["message"]), account.key).signature.hex()
        verified_wallet = client.post("/api/users/wallets/verify", headers=earner, json={
            "challenge_id": challenge.json()["challenge_id"], "address": account.address, "signature": signed,
            "wallet_client_type": "metamask", "connector_type": "injected", "chain_id": 43114, "make_primary": True
        })
        assert verified_wallet.status_code == 200

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
            "missions": [
                {"title": "Learn", "description": "Read briefing", "mission_type": "LEARN", "verification_type": "SELF_ATTEST", "xp_reward": 50},
                {"title": "Verify", "description": "Answer token symbol", "mission_type": "LEARN", "verification_type": "QUIZ", "quiz_question": "Token symbol?", "quiz_options": ["TBAG", "BTC"], "quiz_answer": "TBAG", "xp_reward": 75}
            ]
        })
        assert campaign.status_code == 200
        campaign_id = campaign.json()["id"]

        unfunded_live = client.patch(f"/api/admin/campaigns/{campaign_id}", headers=admin, json={"status": "LIVE"})
        assert unfunded_live.status_code == 400
        declared = client.post(f"/api/funding/campaigns/{campaign_id}/declare", headers=creator, json={"amount": 100000, "tx_hash": "0xtestfunding"})
        assert declared.status_code == 200
        verified = client.post(f"/api/funding/campaigns/{campaign_id}/verify", headers=admin, json={"amount": 100000, "tx_hash": "0xtestfunding"})
        assert verified.status_code == 200 and verified.json()["fully_funded"] is True
        assert client.patch(f"/api/admin/campaigns/{campaign_id}", headers=admin, json={"status": "LIVE"}).status_code == 200
        assert client.post(f"/api/campaigns/{campaign_id}/enroll", headers=earner).status_code == 200

        missions = client.get(f"/api/campaigns/{campaign_id}").json()["missions"]
        rule = client.post("/api/onchain/rules", headers=creator, json={"mission_id": missions[0]["id"], "chain": "Avalanche", "rule_type": "TX_SUCCESS"})
        assert rule.status_code == 200
        rule_id = rule.json()["id"]
        blocked = client.post(f"/api/campaigns/{campaign_id}/missions/{missions[0]['id']}/complete", headers=earner, json={"answer": None})
        assert blocked.status_code == 400 and "on-chain verification" in blocked.json()["detail"]

        def fake_rpc(chain, method, params):
            if method == "eth_getTransactionReceipt":
                return {"status": "0x1"}
            if method == "eth_getTransactionByHash":
                return {"from": account.address, "to": "0x2222222222222222222222222222222222222222"}
            raise AssertionError(f"Unexpected RPC method {method}")

        onchain_router.rpc_call = fake_rpc
        proof = client.post(f"/api/onchain/rules/{rule_id}/verify", headers=earner, json={"tx_hash": "0xsuccessfultransaction"})
        assert proof.status_code == 200 and proof.json()["verified"] is True

        assert client.post(f"/api/campaigns/{campaign_id}/missions/{missions[0]['id']}/complete", headers=earner, json={"answer": None}).status_code == 200
        assert client.post(f"/api/campaigns/{campaign_id}/missions/{missions[1]['id']}/complete", headers=earner, json={"answer": "TBAG"}).status_code == 200

        balances = client.get("/api/users/dashboard", headers=earner).json()["balances"]
        assert any(item["asset_symbol"] == "TBAG" and float(item["amount"]) == 80 for item in balances)
        treasury = client.get("/api/admin/treasury", headers=admin).json()
        assert any(item["asset"] == "TBAG" and float(item["amount"]) == 20 for item in treasury)

        price = client.post("/api/prices/snapshot", headers=admin, json={"asset": "TBAG", "price_gbp": 0.1, "source": "TEST"})
        assert price.status_code == 200
        earnings = client.get("/api/earnings/summary", headers=earner)
        assert earnings.status_code == 200
        valuation = next(item for item in earnings.json()["valuations"] if item["asset"] == "TBAG")
        assert float(valuation["current_value_gbp"]) == 8.0
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
        assert any(item["asset_symbol"] == "TBAG" and float(item["amount"]) == 82 for item in balances)
