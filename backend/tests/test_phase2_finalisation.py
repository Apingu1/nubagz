from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.abuse_models import SecurityEvent
from app.admin_user_models import AdminUserAction
from app.challenge_models import SocialAccount
from app.db import SessionLocal
from app.main import app
from app.models import User, UserSession, WalletConnection
from app.security_models import PrivyIdentityBinding


def register(client: TestClient, email: str, username: str, password: str = "Phase2Finish123!"):
    response = client.post("/api/auth/register", json={"email": email, "username": username, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


def admin_login(client: TestClient):
    response = client.post("/api/auth/login", json={"email": "admin@demo.nubagz.com", "password": "Admin123!"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_login_history_records_success_and_failed_attempts_without_raw_network_data():
    with TestClient(app) as client:
        user_id, _ = register(client, "phase2-history@example.com", "Phase2History")
        bad = client.post("/api/auth/login", json={"email": "phase2-history@example.com", "password": "definitely-wrong"})
        assert bad.status_code == 401
        good = client.post("/api/auth/login", json={"email": "phase2-history@example.com", "password": "Phase2Finish123!"})
        assert good.status_code == 200

        with SessionLocal() as db:
            events = db.query(SecurityEvent).filter(SecurityEvent.user_id == user_id).order_by(SecurityEvent.id).all()
            types = [row.event_type for row in events]
            assert types.count("LOGIN_SUCCESS") >= 2  # registration session + explicit login
            assert "LOGIN_FAILED" in types
            assert all(len(row.ip_hash) == 64 for row in events)
            assert all("127.0.0.1" not in row.ip_hash and "testclient" not in row.ip_hash for row in events)


def test_wallet_role_changes_are_recorded_as_security_history():
    with TestClient(app) as client:
        user_id, headers = register(client, "phase2-wallet-history@example.com", "Phase2WalletHistory")
        with SessionLocal() as db:
            first = WalletConnection(
                user_id=user_id,
                address="0x1111111111111111111111111111111111111111",
                verified_at=datetime.now(UTC),
                wallet_client_type="metamask",
                connector_type="injected",
                is_primary_interactive=True,
                is_primary=True,
            )
            second = WalletConnection(
                user_id=user_id,
                address="0x2222222222222222222222222222222222222222",
                verified_at=datetime.now(UTC),
                wallet_client_type="rabby",
                connector_type="injected",
            )
            db.add_all([first, second])
            user = db.get(User, user_id)
            user.wallet_address = first.address
            user.wallet_chain = "EVM"
            db.commit()
            second_id = second.id

        signer = client.post(f"/api/users/wallets/{second_id}/interactive-primary", headers=headers)
        assert signer.status_code == 200, signer.text
        rewards = client.post(f"/api/users/wallets/{second_id}/primary", headers=headers)
        assert rewards.status_code == 200, rewards.text

        with SessionLocal() as db:
            types = {
                row.event_type
                for row in db.query(SecurityEvent).filter(SecurityEvent.user_id == user_id).all()
            }
            assert "INTERACTIVE_SIGNER_CHANGED" in types
            assert "REWARD_DESTINATION_CHANGED" in types


def test_admin_can_replace_compromised_connected_login_with_reason_and_revoke_sessions():
    with TestClient(app) as client:
        target_id, _ = register(client, "phase2-recovery-login@example.com", "Phase2RecoveryLogin")
        with SessionLocal() as db:
            db.add(PrivyIdentityBinding(user_id=target_id, privy_user_id="did:privy:old-phase2-user"))
            db.add(SocialAccount(
                user_id=target_id,
                provider="X",
                provider_user_id="x-old-phase2-user",
                privy_user_id="did:privy:old-phase2-user",
                username="oldphase2",
            ))
            db.commit()

        admin = admin_login(client)
        response = client.post(
            f"/api/admin/recovery/users/{target_id}/connected-login/replace",
            headers=admin,
            json={
                "new_privy_user_id": "did:privy:replacement-phase2-user",
                "reason": "Support verified the replacement Privy identity after account compromise.",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["sessions_revoked"] >= 1

        with SessionLocal() as db:
            binding = db.query(PrivyIdentityBinding).filter(PrivyIdentityBinding.user_id == target_id).one()
            assert binding.privy_user_id == "did:privy:replacement-phase2-user"
            assert db.query(SocialAccount).filter(SocialAccount.user_id == target_id).count() == 0
            active_sessions = db.query(UserSession).filter(UserSession.user_id == target_id, UserSession.revoked_at.is_(None)).count()
            assert active_sessions == 0
            action = db.query(AdminUserAction).filter(
                AdminUserAction.target_user_id == target_id,
                AdminUserAction.action_type == "CONNECTED_LOGIN_REPLACED",
            ).first()
            assert action is not None
            event = db.query(SecurityEvent).filter(
                SecurityEvent.user_id == target_id,
                SecurityEvent.event_type == "CONNECTED_LOGIN_REPLACED",
            ).first()
            assert event is not None


def test_admin_can_retire_compromised_signer_and_promote_verified_replacement():
    with TestClient(app) as client:
        target_id, _ = register(client, "phase2-recovery-wallet@example.com", "Phase2RecoveryWallet")
        with SessionLocal() as db:
            compromised = WalletConnection(
                user_id=target_id,
                address="0x3333333333333333333333333333333333333333",
                verified_at=datetime.now(UTC),
                wallet_client_type="metamask",
                connector_type="injected",
                is_primary_interactive=True,
                is_primary=True,
            )
            replacement = WalletConnection(
                user_id=target_id,
                address="0x4444444444444444444444444444444444444444",
                verified_at=datetime.now(UTC),
                wallet_client_type="rabby",
                connector_type="injected",
            )
            db.add_all([compromised, replacement])
            user = db.get(User, target_id)
            user.wallet_address = compromised.address
            user.wallet_chain = "EVM"
            db.commit()
            compromised_id = compromised.id
            replacement_id = replacement.id

        # Create a fresh target session so the recovery path proves revocation.
        fresh = client.post("/api/auth/login", json={"email": "phase2-recovery-wallet@example.com", "password": "Phase2Finish123!"})
        assert fresh.status_code == 200
        admin = admin_login(client)
        response = client.post(
            f"/api/admin/recovery/users/{target_id}/wallets/{compromised_id}/retire",
            headers=admin,
            json={
                "replacement_wallet_id": replacement_id,
                "reason": "Support confirmed the original signer was compromised and the replacement was already verified.",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["replacement_wallet_id"] == replacement_id
        assert response.json()["sessions_revoked"] >= 1

        with SessionLocal() as db:
            assert db.get(WalletConnection, compromised_id) is None
            replacement = db.get(WalletConnection, replacement_id)
            assert replacement is not None
            assert replacement.is_primary_interactive is True
            assert replacement.is_primary is True
            user = db.get(User, target_id)
            assert user.wallet_address.lower() == replacement.address.lower()
            assert db.query(UserSession).filter(UserSession.user_id == target_id, UserSession.revoked_at.is_(None)).count() == 0
            assert db.query(AdminUserAction).filter(
                AdminUserAction.target_user_id == target_id,
                AdminUserAction.action_type == "COMPROMISED_WALLET_RETIRED",
            ).first() is not None


def test_support_role_can_investigate_users_but_cannot_mutate_accounts():
    with TestClient(app) as client:
        support_id, support_headers = register(client, "phase2-support@example.com", "Phase2Support")
        target_id, _ = register(client, "phase2-support-target@example.com", "Phase2SupportTarget")
        with SessionLocal() as db:
            support = db.get(User, support_id)
            support.role = "SUPPORT"
            db.commit()

        directory = client.get("/api/admin/users", headers=support_headers)
        assert directory.status_code == 200, directory.text
        history = client.get(f"/api/admin/recovery/users/{target_id}/history", headers=support_headers)
        assert history.status_code == 200, history.text
        assert history.json()["role"] == "SUPPORT"
        assert "users.view" in history.json()["permissions"]

        mutation = client.patch(
            f"/api/admin/users/{target_id}/state",
            headers=support_headers,
            json={"account_state": "RESTRICTED", "reason": "Support must not be able to change account state."},
        )
        assert mutation.status_code == 403
        recovery = client.post(
            f"/api/admin/recovery/users/{target_id}/connected-login/replace",
            headers=support_headers,
            json={"new_privy_user_id": "did:privy:support-cannot-rebind", "reason": "Support role is read only by design."},
        )
        assert recovery.status_code == 403
