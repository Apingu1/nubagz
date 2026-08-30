import hashlib
import json
import re
import secrets
from datetime import datetime, UTC
import jwt
from jwt.algorithms import ECAlgorithm
from fastapi import HTTPException
from sqlalchemy.orm import Session
from .challenge_models import SocialAccount
from .config import settings
from .models import User
from .security_models import PrivyIdentityBinding
from .security import hash_password
from .utils import unique_referral_code


PROVIDER_TYPES = {
    "google_oauth": "GOOGLE",
    "twitter_oauth": "X",
}


def _verification_key():
    raw = (settings.privy_verification_key or "").strip()
    if not raw:
        raise HTTPException(503, "Privy identity-token verification is not configured")
    raw = raw.replace("\\n", "\n")
    if raw.startswith("{"):
        try:
            return ECAlgorithm.from_jwk(raw)
        except Exception as exc:
            raise HTTPException(503, "PRIVY_VERIFICATION_KEY is not a valid EC JWK") from exc
    return raw


def verify_privy_identity_token(identity_token: str) -> tuple[str, list[dict]]:
    if not settings.privy_app_id:
        raise HTTPException(503, "PRIVY_APP_ID is not configured")
    try:
        payload = jwt.decode(
            identity_token,
            _verification_key(),
            algorithms=["ES256"],
            audience=settings.privy_app_id,
            issuer="privy.io",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid or expired Privy identity token") from exc

    privy_user_id = str(payload.get("sub") or "").strip()
    if not privy_user_id:
        raise HTTPException(401, "Privy identity token is missing its user id")

    linked = payload.get("linked_accounts", "[]")
    try:
        accounts = json.loads(linked) if isinstance(linked, str) else linked
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(401, "Privy identity token contains invalid linked accounts") from exc
    if not isinstance(accounts, list):
        raise HTTPException(401, "Privy identity token contains invalid linked accounts")
    return privy_user_id, accounts


def normalized_social_accounts(accounts: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        provider = PROVIDER_TYPES.get(str(account.get("type") or ""))
        subject = str(account.get("subject") or "").strip()
        if not provider or not subject:
            continue
        rows.append({
            "provider": provider,
            "provider_user_id": subject,
            "username": account.get("username"),
            "email": account.get("email"),
            "display_name": account.get("name") or account.get("displayName"),
            "profile_picture_url": account.get("profilePictureUrl") or account.get("profile_picture_url"),
        })
    return rows


def find_social_user(db: Session, privy_user_id: str, accounts: list[dict]) -> User | None:
    social = normalized_social_accounts(accounts)
    user_ids: set[int] = set()
    binding = db.query(PrivyIdentityBinding).filter(PrivyIdentityBinding.privy_user_id == privy_user_id).first()
    if binding:
        user_ids.add(binding.user_id)
    # Compatibility lookup for pre-2.1 records before the canonical binding has
    # been backfilled by a successful login/link operation.
    user_ids.update(
        row.user_id for row in db.query(SocialAccount).filter(SocialAccount.privy_user_id == privy_user_id).all()
    )
    for account in social:
        existing = db.query(SocialAccount).filter(
            SocialAccount.provider == account["provider"],
            SocialAccount.provider_user_id == account["provider_user_id"],
        ).first()
        if existing:
            user_ids.add(existing.user_id)
    if len(user_ids) > 1:
        raise HTTPException(409, "These linked identities are already attached to different NuBagz users")
    return db.get(User, next(iter(user_ids))) if user_ids else None


def _unique_username(db: Session, preferred: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]", "", preferred or "")[:48]
    if len(clean) < 3:
        clean = f"BagUser{secrets.token_hex(3)}"
    candidate = clean
    suffix = 2
    while db.query(User).filter(User.username == candidate).first():
        candidate = f"{clean[:55]}{suffix}"
        suffix += 1
    return candidate[:64]


def _synthetic_email(provider: str, subject: str) -> str:
    digest = hashlib.sha256(f"{provider}:{subject}".encode()).hexdigest()[:20]
    return f"social-{provider.lower()}-{digest}@users.nubagz.local"


def create_social_user(db: Session, accounts: list[dict], referred_by_id: int | None = None) -> User:
    social = normalized_social_accounts(accounts)
    if not social:
        raise HTTPException(400, "No supported Google or X identity was found")
    primary = social[0]
    preferred_email = str(primary.get("email") or "").lower().strip()
    if not preferred_email or db.query(User).filter(User.email == preferred_email).first():
        preferred_email = _synthetic_email(primary["provider"], primary["provider_user_id"])
    preferred_name = str(primary.get("username") or primary.get("display_name") or f"Bag{primary['provider']}")
    username = _unique_username(db, preferred_name)
    user = User(
        email=preferred_email,
        username=username,
        password_hash=hash_password(secrets.token_urlsafe(48)),
        referral_code=unique_referral_code(db, username),
        referred_by_id=referred_by_id,
        streak_days=1,
        account_state="ACTIVE",
    )
    db.add(user)
    db.flush()
    return user


def sync_social_accounts(db: Session, user: User, privy_user_id: str, accounts: list[dict]) -> list[SocialAccount]:
    social = normalized_social_accounts(accounts)
    now = datetime.now(UTC)

    did_owner = db.query(PrivyIdentityBinding).filter(PrivyIdentityBinding.privy_user_id == privy_user_id).first()
    if did_owner and did_owner.user_id != user.id:
        raise HTTPException(409, "That Privy identity is already bound to another NuBagz user")
    binding = db.query(PrivyIdentityBinding).filter(PrivyIdentityBinding.user_id == user.id).first()
    if binding and binding.privy_user_id != privy_user_id:
        raise HTTPException(409, "This NuBagz account is already bound to a different Privy identity")
    if not binding:
        binding = PrivyIdentityBinding(user_id=user.id, privy_user_id=privy_user_id, created_at=now, last_verified_at=now)
        db.add(binding)
    else:
        binding.last_verified_at = now

    for account in social:
        identity_owner = db.query(SocialAccount).filter(
            SocialAccount.provider == account["provider"],
            SocialAccount.provider_user_id == account["provider_user_id"],
        ).first()
        if identity_owner and identity_owner.user_id != user.id:
            raise HTTPException(409, f"That {account['provider']} account is already linked to another NuBagz user")

        row = db.query(SocialAccount).filter(
            SocialAccount.user_id == user.id,
            SocialAccount.provider == account["provider"],
        ).first()
        if row and row.provider_user_id != account["provider_user_id"]:
            raise HTTPException(409, f"A different {account['provider']} account is already linked to this NuBagz user")
        if not row:
            row = SocialAccount(
                user_id=user.id,
                provider=account["provider"],
                provider_user_id=account["provider_user_id"],
                privy_user_id=privy_user_id,
            )
            db.add(row)
        row.provider_user_id = account["provider_user_id"]
        row.privy_user_id = privy_user_id
        row.username = account.get("username")
        row.email = account.get("email")
        row.display_name = account.get("display_name")
        row.profile_picture_url = account.get("profile_picture_url")
        row.last_verified_at = now
    db.flush()
    return db.query(SocialAccount).filter(SocialAccount.user_id == user.id).order_by(SocialAccount.provider).all()
