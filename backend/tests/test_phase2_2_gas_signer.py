from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import User, WalletConnection
from app.routers.gas_security import _interactive_wallet


def test_sponsored_gas_selects_interactive_signer_not_reward_primary_wallet():
    with TestClient(app) as client:
        signup = client.post('/api/auth/register', json={
            'email': 'phase22-gas-signer@example.com',
            'username': 'Phase22GasSigner',
            'password': 'Phase22GasSigner123!',
        })
        assert signup.status_code == 200, signup.text
        user_id = signup.json()['user']['id']

        with SessionLocal() as db:
            reward_wallet = WalletConnection(
                user_id=user_id,
                address='0x6666666666666666666666666666666666666666',
                chain_type='ethereum',
                chain_id=43114,
                wallet_client_type='metamask',
                connector_type='injected',
                wallet_type='EXTERNAL',
                is_primary=True,
                is_primary_interactive=False,
                verified_at=datetime.now(UTC),
                last_connected_at=datetime.now(UTC),
            )
            signer_wallet = WalletConnection(
                user_id=user_id,
                address='0x7777777777777777777777777777777777777777',
                chain_type='ethereum',
                chain_id=43114,
                wallet_client_type='rabby',
                connector_type='injected',
                wallet_type='EXTERNAL',
                is_primary=False,
                is_primary_interactive=True,
                verified_at=datetime.now(UTC),
                last_connected_at=datetime.now(UTC),
            )
            db.add_all([reward_wallet, signer_wallet])
            db.commit()
            user = db.get(User, user_id)
            selected = _interactive_wallet(db, user)
            assert selected.address == signer_wallet.address
            assert selected.is_primary_interactive is True
            assert selected.is_primary is False
