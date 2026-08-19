from datetime import datetime, UTC
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import User
from ..schemas import RegisterIn, LoginIn, AuthOut, UserOut, WalletUpdate
from ..security import hash_password, verify_password, create_access_token
from ..utils import unique_referral_code
from ..deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=AuthOut)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email.lower()).first():
        raise HTTPException(409, "Email already registered")
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(409, "Username already taken")
    referred_by = None
    if data.referral_code:
        referred_by = db.query(User).filter(User.referral_code == data.referral_code.upper()).first()
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
    user.last_active_at = datetime.now(UTC)
    db.commit()
    return AuthOut(access_token=create_access_token(user.id, user.role), user=UserOut.model_validate(user))


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
