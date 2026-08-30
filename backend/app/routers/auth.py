import secrets
from datetime import datetime, UTC, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User, UserSession
from ..challenge_models import SocialAccount
from ..risk_models import UserTrustProfile
from ..schemas import RegisterIn, LoginIn, AuthOut, UserOut, PrivyAuthIn, SocialAccountSyncIn, SocialAccountOut
from ..security import hash_password, verify_password, create_access_token
from ..security_hardening import record_security_event, trusted_client_ip
from ..social_auth import create_social_user, find_social_user, sync_social_accounts, verify_privy_identity_token
from ..utils import unique_referral_code
from ..deps import get_current_user, get_current_session
from ..config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
REFERRAL_ELIGIBLE_LEVELS = {"NORMAL", "VERIFIED"}
BLOCKED_LOGIN_STATES = {"SUSPENDED", "DISQUALIFIED"}


def _security_event(request: Request, user_id: int | None, event_type: str, detail: str) -> None:
    record_security_event(
        user_id=user_id,
        network_value=trusted_client_ip(request),
        event_type=event_type,
        route_group="AUTH",
        detail=detail,
    )


def _resolve_referrer(db: Session, referral_code: str | None) -> User | None:
    if not referral_code:
        return None
    referred_by = db.query(User).filter(User.referral_code == referral_code.upper()).first()
    if not referred_by or not referred_by.is_active or referred_by.account_state in BLOCKED_LOGIN_STATES:
        raise HTTPException(400, "Referral code is not valid or is no longer active")
    referrer_profile = db.query(UserTrustProfile).filter(UserTrustProfile.user_id == referred_by.id).first()
    if referrer_profile and referrer_profile.trust_level not in REFERRAL_ELIGIBLE_LEVELS:
        raise HTTPException(400, "This referral code is temporarily not eligible for attribution while the referrer is under trust review")
    return referred_by


def _start_session(db: Session, user: User, auth_method: str) -> tuple[str, UserSession]:
    now = datetime.now(UTC)
    session = UserSession(
        session_id=secrets.token_urlsafe(32),
        user_id=user.id,
        auth_method=auth_method,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(minutes=settings.access_token_minutes),
    )
    db.add(session)
    db.flush()
    token = create_access_token(user.id, user.role, session.session_id)
    return token, session


@router.post("/register", response_model=AuthOut)
def register(data: RegisterIn, request: Request, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email.lower()).first():
        _security_event(request, None, "REGISTER_BLOCKED_DUPLICATE", "Registration was rejected because the submitted email is already registered.")
        raise HTTPException(409, "Email already registered")
    if db.query(User).filter(User.username == data.username).first():
        _security_event(request, None, "REGISTER_BLOCKED_DUPLICATE", "Registration was rejected because the submitted username is already registered.")
        raise HTTPException(409, "Username already taken")
    referred_by = _resolve_referrer(db, data.referral_code)
    user = User(
        email=data.email.lower(),
        username=data.username,
        password_hash=hash_password(data.password),
        referral_code=unique_referral_code(db, data.username),
        referred_by_id=referred_by.id if referred_by else None,
        streak_days=1,
        account_state="ACTIVE",
    )
    db.add(user)
    db.flush()
    token, session = _start_session(db, user, "PASSWORD")
    db.commit()
    db.refresh(user)
    _security_event(request, user.id, "LOGIN_SUCCESS", f"Password registration created session {session.session_id[:12]}…")
    return AuthOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthOut)
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email.lower()).first()
    if not user or not verify_password(data.password, user.password_hash):
        _security_event(request, user.id if user else None, "LOGIN_FAILED", "Password login failed because credentials were invalid.")
        raise HTTPException(401, "Invalid email or password")
    if not user.is_active or user.account_state in BLOCKED_LOGIN_STATES:
        _security_event(request, user.id, "LOGIN_BLOCKED_ACCOUNT_STATE", f"Password login blocked while account state is {user.account_state}.")
        raise HTTPException(403, "This NuBagz account is not available for login")
    user.last_active_at = datetime.now(UTC)
    token, session = _start_session(db, user, "PASSWORD")
    db.commit()
    _security_event(request, user.id, "LOGIN_SUCCESS", f"Password login created session {session.session_id[:12]}…")
    return AuthOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/privy", response_model=AuthOut)
def privy_social_login(data: PrivyAuthIn, request: Request, db: Session = Depends(get_db)):
    """Exchange a verified Privy Google/X identity for the NuBagz API JWT.

    NuBagz deliberately does not merge an OAuth login into an existing local
    account merely because the email strings match. Existing users link social
    accounts from inside My Bag, preventing an unverified legacy email from
    becoming an account-takeover path.
    """
    try:
        privy_user_id, linked_accounts = verify_privy_identity_token(data.identity_token)
    except HTTPException:
        _security_event(request, None, "PRIVY_LOGIN_FAILED", "Privy login failed identity-token verification.")
        raise
    user = find_social_user(db, privy_user_id, linked_accounts)
    if user and (not user.is_active or user.account_state in BLOCKED_LOGIN_STATES):
        _security_event(request, user.id, "LOGIN_BLOCKED_ACCOUNT_STATE", f"Privy login blocked while account state is {user.account_state}.")
        raise HTTPException(403, "This NuBagz account is not available for login")
    if not user:
        referred_by = _resolve_referrer(db, data.referral_code)
        user = create_social_user(db, linked_accounts, referred_by.id if referred_by else None)
    sync_social_accounts(db, user, privy_user_id, linked_accounts)
    user.last_active_at = datetime.now(UTC)
    db.flush()
    token, session = _start_session(db, user, "PRIVY")
    db.commit()
    db.refresh(user)
    _security_event(request, user.id, "LOGIN_SUCCESS", f"Privy login created session {session.session_id[:12]}…")
    return AuthOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    db: Session = Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    user_id = session.user_id
    session_id = session.session_id
    if session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        session.revoke_reason = "USER_LOGOUT"
        db.commit()
    _security_event(request, user_id, "LOGOUT", f"User logout revoked session {session_id[:12]}…")
    return None


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
