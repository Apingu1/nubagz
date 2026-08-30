from datetime import timedelta
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..challenge_models import Challenge
from ..db import get_db
from ..deps import get_current_user
from ..integration_models import GasSponsorshipClaim, GasSponsorshipPolicy
from ..models import Campaign, Project, User, WalletConnection
from . import gas as gas_routes


router = APIRouter(prefix="/api/gas", tags=["sponsored-gas-security"])


def _interactive_wallet(db: Session, user: User) -> WalletConnection:
    wallet = db.query(WalletConnection).filter(
        WalletConnection.user_id == user.id,
        WalletConnection.is_primary_interactive.is_(True),
        WalletConnection.verified_at.isnot(None),
    ).order_by(WalletConnection.verified_at.desc()).first()
    if not wallet:
        raise HTTPException(409, "Connect and verify an interactive EVM wallet before using sponsored gas")
    return wallet


@router.post("/challenges/{challenge_id}/prepare")
def prepare_sponsorship_with_interactive_signer(
    challenge_id: int,
    _: gas_routes.PrepareIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Phase 2.2 secure entry point for Sponsored Gas.

    The legacy implementation selected the reward-primary verified wallet. That is
    no longer a valid identity rule: Sponsored Gas belongs to an on-chain
    Challenge, so its reservation must be tied to the selected verified
    interactive signer. Reward destinations remain independent.
    """
    challenge = db.get(Challenge, challenge_id)
    campaign = db.get(Campaign, challenge.campaign_id) if challenge else None
    project = db.get(Project, campaign.project_id) if campaign else None
    if (
        not challenge
        or challenge.category != "ONCHAIN"
        or challenge.status != "ACTIVE"
        or not campaign
        or campaign.status != "LIVE"
        or not project
        or project.status not in gas_routes.PUBLIC_PROJECT_STATUSES
    ):
        raise HTTPException(404, "Live on-chain Bag Work not found")

    gas_routes._require_enrollment(db, user, campaign)
    transaction = gas_routes._build_transaction(
        challenge,
        str((challenge.config or {}).get("chain") or project.chain),
    )
    policy = db.query(GasSponsorshipPolicy).filter(
        GasSponsorshipPolicy.challenge_id == challenge.id
    ).with_for_update().first()
    if not policy:
        return {"mode": "USER_PAID", "reason": "NO_SPONSORSHIP", "transaction": transaction}

    wallet = _interactive_wallet(db, user)
    existing = gas_routes._active_reservation(db, policy.id, user.id)
    if existing:
        if existing.wallet_connection_id != wallet.id or json.loads(existing.transaction_payload) != transaction:
            existing.status = "RELEASED"
            db.flush()
        else:
            payload = gas_routes._claim_payload(existing, db)
            db.commit()
            return payload

    reason, cap = gas_routes._policy_reason(db, policy, user.id)
    if reason:
        db.commit()
        return {"mode": "USER_PAID", "reason": reason, "transaction": transaction}

    row = GasSponsorshipClaim(
        policy_id=policy.id,
        challenge_id=challenge.id,
        campaign_id=campaign.id,
        user_id=user.id,
        wallet_connection_id=wallet.id,
        reservation_key=secrets.token_urlsafe(32),
        transaction_payload=json.dumps(transaction, separators=(",", ":")),
        reserved_native_amount=cap,
        status="RESERVED",
        reservation_expires_at=gas_routes._now() + timedelta(minutes=10),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return gas_routes._claim_payload(row, db)


@router.post("/claims/{claim_id}/execute")
def execute_sponsorship_with_same_interactive_signer(
    claim_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    claim = db.query(GasSponsorshipClaim).filter(
        GasSponsorshipClaim.id == claim_id,
        GasSponsorshipClaim.user_id == user.id,
    ).first()
    if claim and claim.status == "RESERVED":
        wallet = db.get(WalletConnection, claim.wallet_connection_id)
        if (
            not wallet
            or wallet.user_id != user.id
            or not wallet.verified_at
            or not wallet.is_primary_interactive
        ):
            raise HTTPException(
                409,
                "This Sponsored Gas reservation is no longer tied to your selected interactive signer. Prepare the Challenge again.",
            )
    return gas_routes.execute_sponsorship(claim_id=claim_id, db=db, user=user)
