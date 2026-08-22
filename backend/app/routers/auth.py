from datetime import datetime, UTC
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import User
from ..challenge_models import SocialAccount
from ..risk_models import UserTrustProfile
from ..schemas import RegisterIn, LoginIn, AuthOut, UserOut, WalletUpdate, PrivyAuthIn, SocialAccountSyncIn, SocialAccountOut
from ..security import hash_password, verify_password, create_access_token
from ..social_auth import create_social_user, find_social_user, sync_social_accounts, verify_privy_identity_token
from ..utils import unique_referral_code
from ..deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])
REFERRAL_ELIGIBLE_LEVELS = {"NORMAL", "VERIFIED"}


def _resolve_referrer(db: Session, referral_code: str | None) -> User | None:
    if not referral_code:
        return None
    referred_by = db.query(User).filter(User.referral_code == referral_code.upper()).first()
    if not referred_by or not referred_by.is_active:
        raise HTTPException(400, "Referral code is not valid or is no longer active")
    referrer_profile = db.query(UserTrustProfile).filter(UserTrustProfile.user_id == referred_by.id).first()
    if referrer_profile and referrer_profile.trust_level not in REFERRAL_ELIGIBLE_LEVELS:
        raise HTTPException(400, "This referral code is temporarily not eligible for attribution while the referrer is under trust review")
    return referred_by


@router.post("/register", response_model=AuthOut)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email.lower()).first():
        raise HTTPException(409, "Email already registered")
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(409, "Username already taken")
    referred_by = _resolve_referrer(db, data.referral_code)
    user = User(
        email=data.email.lower(),
        username=data.username,
        password_hash=hash_password(data.password),
        referral_code=unique_referral_code(db, data.username),
        referred_by_id=referred_by.id if referred_by else None,
        streak_days=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id, user.role)
    return AuthOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email.lower()).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(403, "This NuBagz account is inactive")
    user.last_active_at = datetime.now(UTC)
    db.commit()
    return AuthOut(access_token=create_access_token(user.id, user.role), user=UserOut.model_validate(user))


@router.post("/privy", response_model=AuthOut)
def privy_social_login(data: PrivyAuthIn, db: Session = Depends(get_db)):
    """Exchange a verified Privy Google/X/TikTok identity for the NuBagz API JWT.

    NuBagz deliberately does not merge an OAuth login into an existing local
    account merely because the email strings match. Existing users link social
    accounts from inside My Bag, preventing an unverified legacy email from
    becoming an account-takeover path.
    """
    privy_user_id, linked_accounts = verify_privy_identity_token(data.identity_token)
    user = find_social_user(db, privy_user_id, linked_accounts)
    if user and not user.is_active:
        raise HTTPException(403, "This NuBagz account is inactive")
    if not user:
        referred_by = _resolve_referrer(db, data.referral_code)
        user = create_social_user(db, linked_accounts, referred_by.id if referred_by else None)
    sync_social_accounts(db, user, privy_user_id, linked_accounts)
    user.last_active_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)
    return AuthOut(access_token=create_access_token(user.id, user.role), user=UserOut.model_validate(user))


@router.post("/social-accounts/sync", response_model=list[SocialAccountOut])
def sync_linked_social_accounts(
    data: SocialAccountSyncIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    privy_user_id, linked_accounts = verify_privy_identity_token(data.identity_token)
    rows = sync_social_accounts(db, user, privy_user_id, linked_accounts)
    db.commit()
    return rows


@router.get("/social-accounts", response_model=list[SocialAccountOut])
def social_accounts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(SocialAccount).filter(SocialAccount.user_id == user.id).order_by(SocialAccount.provider).all()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.put("/wallet", response_model=UserOut)
def update_wallet(data: WalletUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    user.wallet_address = data.wallet_address.strip()
    user.wallet_chain = data.wallet_chain.strip()
    db.commit()
    db.refresh(user)
    return user
