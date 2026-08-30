from sqlalchemy.orm import Session

from .account_policy import EARN_REWARDS, allows
from .challenge_models import Challenge, SocialAccount
from .models import User, WalletConnection


SUPPORTED_SOCIAL_DEPENDENCIES = {"X", "GOOGLE"}


def _upper(value: object) -> str:
    return str(value or "").strip().upper()


def requirement_codes(challenge: Challenge) -> list[str]:
    """Derive identity/capability dependencies from the Challenge itself.

    Phase 2.2 deliberately keeps this deterministic and schema-light. Phase 3 can
    persist richer requirement definitions, but current Challenge types already
    carry enough category/provider/action information to avoid hard-coding gates
    separately throughout the API and frontend.
    """
    category = _upper(challenge.category)
    provider = _upper(challenge.provider)
    action = _upper(challenge.action)
    codes: list[str] = ["ACCOUNT_REWARD_ELIGIBLE"]

    if category == "ONCHAIN":
        codes.append("INTERACTIVE_WALLET")

    if category == "SOCIAL" and provider in SUPPORTED_SOCIAL_DEPENDENCIES:
        codes.append(f"SOCIAL_{provider}")

    # Future/current NuBagz Swap Challenges can identify themselves through the
    # category, provider or action without requiring another special-case route.
    if category == "SWAP" or provider in {"NUBAGZ_SWAP", "SWAP"} or action == "SWAP":
        if "INTERACTIVE_WALLET" not in codes:
            codes.append("INTERACTIVE_WALLET")
        codes.append("ACTIVE_SIGNER")

    return codes


def _interactive_wallet(db: Session, user: User) -> WalletConnection | None:
    return db.query(WalletConnection).filter(
        WalletConnection.user_id == user.id,
        WalletConnection.is_primary_interactive.is_(True),
        WalletConnection.verified_at.isnot(None),
    ).order_by(WalletConnection.verified_at.desc()).first()


def _social_account(db: Session, user: User, provider: str) -> SocialAccount | None:
    return db.query(SocialAccount).filter(
        SocialAccount.user_id == user.id,
        SocialAccount.provider == provider,
    ).first()


def dependency_preflight(db: Session, user: User, challenge: Challenge) -> dict:
    wallet = _interactive_wallet(db, user)
    requirements = []
    server_ready = True
    active_signer_required = False

    for code in requirement_codes(challenge):
        if code == "ACCOUNT_REWARD_ELIGIBLE":
            satisfied = allows(user, EARN_REWARDS)
            requirements.append({
                "code": code,
                "label": "Account eligible for reward-bearing activity",
                "satisfied": satisfied,
                "detail": "This account can start new reward-bearing Challenges." if satisfied else "This account is restricted from starting new reward-bearing Challenges.",
                "action_path": "/app/account-trust" if not satisfied else None,
                "live_check_required": False,
            })
            server_ready = server_ready and satisfied
        elif code == "INTERACTIVE_WALLET":
            satisfied = wallet is not None
            requirements.append({
                "code": code,
                "label": "Verified interactive wallet",
                "satisfied": satisfied,
                "detail": "A verified signer wallet is available for wallet-dependent activity." if satisfied else "Connect and verify an interactive wallet. A payout-only reward address is not wallet ownership proof.",
                "action_path": "/wallet-setup" if not satisfied else None,
                "live_check_required": False,
            })
            server_ready = server_ready and satisfied
        elif code == "SOCIAL_X":
            satisfied = _social_account(db, user, "X") is not None
            requirements.append({
                "code": code,
                "label": "Connected X account",
                "satisfied": satisfied,
                "detail": "Your provider-issued X identity is connected." if satisfied else "Connect X in My Bag before starting this Challenge.",
                "action_path": "/app/bag" if not satisfied else None,
                "live_check_required": False,
            })
            server_ready = server_ready and satisfied
        elif code == "SOCIAL_GOOGLE":
            satisfied = _social_account(db, user, "GOOGLE") is not None
            requirements.append({
                "code": code,
                "label": "Connected Google account",
                "satisfied": satisfied,
                "detail": "Your provider-issued Google identity is connected." if satisfied else "Connect Google in My Bag before starting this Challenge.",
                "action_path": "/app/bag" if not satisfied else None,
                "live_check_required": False,
            })
            server_ready = server_ready and satisfied
        elif code == "ACTIVE_SIGNER":
            active_signer_required = True
            # The API can prove that a verified signer is selected, but only the
            # browser wallet provider can truthfully say it is currently present
            # and available to sign. The frontend therefore performs this final
            # live check against this exact address.
            satisfied = wallet is not None
            requirements.append({
                "code": code,
                "label": "Active connected signer",
                "satisfied": satisfied,
                "detail": "Open the exact verified signer wallet in NuBagz before executing this action." if satisfied else "Connect and verify an interactive wallet before executing this action.",
                "action_path": "/wallet-setup" if not satisfied else None,
                "live_check_required": True,
            })
            server_ready = server_ready and satisfied

    return {
        "server_ready": server_ready,
        "can_start": server_ready,
        "can_submit": server_ready,
        "active_signer_required": active_signer_required,
        "interactive_wallet_address": wallet.address if wallet else None,
        "requirements": requirements,
    }


def require_server_dependencies(db: Session, user: User, challenge: Challenge) -> dict:
    preflight = dependency_preflight(db, user, challenge)
    for requirement in preflight["requirements"]:
        if requirement["satisfied"]:
            continue
        code = requirement["code"]
        status_code = 403 if code == "ACCOUNT_REWARD_ELIGIBLE" else 409
        from fastapi import HTTPException
        raise HTTPException(status_code=status_code, detail=requirement["detail"])
    return preflight
