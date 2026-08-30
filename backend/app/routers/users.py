from datetime import datetime, timedelta, UTC
from decimal import Decimal
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, LedgerEntry, Enrollment, Withdrawal, WalletConnection, WalletChallenge, PayoutAddress
from ..schemas import DashboardOut, RewardBalance, WithdrawalIn, WalletChallengeIn, WalletVerifyIn, WalletConnectionOut, PayoutAddressIn, PayoutAddressOut

router = APIRouter(prefix="/api/users", tags=["users"])


def _select_reward_wallet(db: Session, user: User, wallet: WalletConnection) -> None:
    db.query(WalletConnection).filter(WalletConnection.user_id == user.id).update({WalletConnection.is_primary: False})
    db.query(PayoutAddress).filter(PayoutAddress.user_id == user.id).update({PayoutAddress.is_primary: False})
    wallet.is_primary = True
    user.wallet_address = wallet.address
    user.wallet_chain = "EVM"


def _select_interactive_wallet(db: Session, user: User, wallet: WalletConnection) -> None:
    db.query(WalletConnection).filter(WalletConnection.user_id == user.id).update({WalletConnection.is_primary_interactive: False})
    wallet.is_primary_interactive = True


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    balances_q=db.query(LedgerEntry.asset_symbol,func.sum(LedgerEntry.amount)).filter(LedgerEntry.user_id==user.id,LedgerEntry.status=="AVAILABLE").group_by(LedgerEntry.asset_symbol).all()
    balances=[RewardBalance(asset_symbol=s,amount=a or 0) for s,a in balances_q]
    active=db.query(func.count(Enrollment.id)).filter(Enrollment.user_id==user.id,Enrollment.status=="ACTIVE").scalar() or 0
    completed=db.query(func.count(Enrollment.id)).filter(Enrollment.user_id==user.id,Enrollment.status=="COMPLETED").scalar() or 0
    recent=db.query(LedgerEntry).filter(LedgerEntry.user_id==user.id).order_by(LedgerEntry.created_at.desc()).limit(8).all()
    return DashboardOut(lifetime_assets=len(balances),active_bagz=active,completed_bagz=completed,xp=user.xp,bag_score=user.bag_score,streak_days=user.streak_days,balances=balances,recent_activity=[{"asset":r.asset_symbol,"amount":str(r.amount),"type":r.entry_type,"status":r.status,"note":r.note,"created_at":r.created_at.isoformat()} for r in recent])


@router.get("/leaderboard")
def leaderboard(db:Session=Depends(get_db)):
    users=db.query(User).filter(User.is_active==True, User.account_state=="ACTIVE").order_by(User.bag_score.desc(),User.xp.desc()).limit(50).all()
    return [{"rank":i+1,"username":u.username,"bag_score":u.bag_score,"xp":u.xp,"streak_days":u.streak_days} for i,u in enumerate(users)]


@router.post("/withdrawals")
def request_withdrawal(data:WithdrawalIn, db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    known_wallet=db.query(WalletConnection).filter(WalletConnection.user_id==user.id,func.lower(WalletConnection.address)==data.wallet_address.lower(),WalletConnection.verified_at.isnot(None)).first()
    known_payout=db.query(PayoutAddress).filter(PayoutAddress.user_id==user.id,PayoutAddress.address==data.wallet_address,PayoutAddress.chain==data.chain).first()
    if not known_wallet and not known_payout:
        raise HTTPException(400,"Choose a saved NuBagz wallet or payout-only reward address before withdrawing")
    available=db.query(func.coalesce(func.sum(LedgerEntry.amount),0)).filter(LedgerEntry.user_id==user.id,LedgerEntry.asset_symbol==data.asset_symbol,LedgerEntry.status=="AVAILABLE").scalar() or Decimal("0")
    reserved=db.query(func.coalesce(func.sum(Withdrawal.amount),0)).filter(Withdrawal.user_id==user.id,Withdrawal.asset_symbol==data.asset_symbol,Withdrawal.status.in_(["PENDING","APPROVED"])).scalar() or Decimal("0")
    if Decimal(available)-Decimal(reserved)<data.amount: raise HTTPException(400,"Insufficient available balance")
    wd=Withdrawal(user_id=user.id,**data.model_dump()); db.add(wd); db.commit(); db.refresh(wd)
    return {"id":wd.id,"status":wd.status,"asset_symbol":wd.asset_symbol,"amount":str(wd.amount)}


@router.get("/wallets",response_model=list[WalletConnectionOut])
def wallets(db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    return db.query(WalletConnection).filter(WalletConnection.user_id==user.id).order_by(WalletConnection.is_primary_interactive.desc(),WalletConnection.is_primary.desc(),WalletConnection.last_connected_at.desc()).all()


@router.post("/wallets/challenge")
def wallet_challenge(data:WalletChallengeIn, db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    nonce=secrets.token_urlsafe(32); issued=datetime.now(UTC)
    message=("NuBagz wallet verification\n\n"f"NuBagz user: {user.username}\n"f"Wallet: {data.address}\n"f"Nonce: {nonce}\n"f"Issued at: {issued.isoformat()}\n\n""Sign this message to prove you control this wallet. This does not authorize a transaction or move funds.")
    challenge=WalletChallenge(user_id=user.id,address=data.address,nonce=nonce,message=message,expires_at=issued+timedelta(minutes=10)); db.add(challenge); db.commit(); db.refresh(challenge)
    return {"challenge_id":challenge.id,"message":message,"expires_at":challenge.expires_at.isoformat()}


@router.post("/wallets/verify",response_model=WalletConnectionOut)
def verify_wallet(data:WalletVerifyIn, db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    challenge=db.query(WalletChallenge).filter(WalletChallenge.id==data.challenge_id,WalletChallenge.user_id==user.id).first(); now_dt=datetime.now(UTC)
    if not challenge or challenge.used_at is not None: raise HTTPException(400,"Wallet verification challenge is invalid or already used")
    expires=challenge.expires_at.replace(tzinfo=UTC) if challenge.expires_at.tzinfo is None else challenge.expires_at
    if expires<now_dt: raise HTTPException(400,"Wallet verification challenge expired")
    if challenge.address.lower()!=data.address.lower(): raise HTTPException(400,"Wallet address does not match the challenge")
    try: recovered=Account.recover_message(encode_defunct(text=challenge.message),signature=data.signature)
    except Exception as exc: raise HTTPException(400,"Wallet signature could not be verified") from exc
    if recovered.lower()!=data.address.lower(): raise HTTPException(400,"Wallet signature does not match this address")
    wallet=db.query(WalletConnection).filter(WalletConnection.user_id==user.id,func.lower(WalletConnection.address)==data.address.lower()).first()
    if not wallet: wallet=WalletConnection(user_id=user.id,address=data.address); db.add(wallet); db.flush()
    wallet.chain_type="ethereum"; wallet.chain_id=data.chain_id; wallet.wallet_client_type=data.wallet_client_type or "unknown"; wallet.connector_type=data.connector_type or "unknown"; wallet.wallet_type="EMBEDDED" if wallet.wallet_client_type=="privy" else "EXTERNAL"; wallet.verified_at=now_dt; wallet.last_connected_at=now_dt; challenge.used_at=now_dt
    current_interactive=db.query(WalletConnection).filter(WalletConnection.user_id==user.id,WalletConnection.is_primary_interactive.is_(True),WalletConnection.verified_at.isnot(None)).first()
    if data.make_primary or not current_interactive:
        _select_interactive_wallet(db,user,wallet)
    # Preserve the onboarding convenience without conflating the two roles:
    # the first verified wallet may become the reward destination, but later
    # payout-only changes never unset the independently selected signer.
    if not user.wallet_address:
        _select_reward_wallet(db,user,wallet)
    db.commit(); db.refresh(wallet); return wallet


@router.post("/wallets/{wallet_id}/interactive-primary")
def make_wallet_interactive_primary(wallet_id:int, db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    wallet=db.query(WalletConnection).filter(WalletConnection.id==wallet_id,WalletConnection.user_id==user.id,WalletConnection.verified_at.isnot(None)).first()
    if not wallet: raise HTTPException(404,"Verified wallet not found")
    _select_interactive_wallet(db,user,wallet); db.commit()
    return {"ok":True,"wallet_id":wallet.id,"role":"INTERACTIVE_SIGNER"}


@router.post("/wallets/{wallet_id}/primary")
def make_wallet_primary(wallet_id:int, db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    wallet=db.query(WalletConnection).filter(WalletConnection.id==wallet_id,WalletConnection.user_id==user.id,WalletConnection.verified_at.isnot(None)).first()
    if not wallet: raise HTTPException(404,"Verified wallet not found")
    _select_reward_wallet(db,user,wallet); db.commit()
    return {"ok":True,"wallet_id":wallet.id,"role":"REWARD_DESTINATION"}


@router.get("/payout-addresses",response_model=list[PayoutAddressOut])
def payout_addresses(db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    return db.query(PayoutAddress).filter(PayoutAddress.user_id==user.id).order_by(PayoutAddress.is_primary.desc(),PayoutAddress.created_at.desc()).all()


@router.post("/payout-addresses",response_model=PayoutAddressOut)
def add_payout_address(data:PayoutAddressIn, db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    existing=db.query(PayoutAddress).filter(PayoutAddress.user_id==user.id,PayoutAddress.chain==data.chain,PayoutAddress.address==data.address).first()
    if existing:
        if data.make_primary:
            db.query(PayoutAddress).filter(PayoutAddress.user_id==user.id).update({PayoutAddress.is_primary:False}); db.query(WalletConnection).filter(WalletConnection.user_id==user.id).update({WalletConnection.is_primary:False}); existing.is_primary=True; user.wallet_address=existing.address; user.wallet_chain=existing.chain; db.commit(); db.refresh(existing)
        return existing
    payout=PayoutAddress(user_id=user.id,address=data.address,chain=data.chain,label=data.label,verification_status="UNVERIFIED")
    db.add(payout); db.flush()
    if data.make_primary or not user.wallet_address:
        db.query(PayoutAddress).filter(PayoutAddress.user_id==user.id).update({PayoutAddress.is_primary:False}); db.query(WalletConnection).filter(WalletConnection.user_id==user.id).update({WalletConnection.is_primary:False}); payout.is_primary=True; user.wallet_address=data.address; user.wallet_chain=data.chain
    db.commit(); db.refresh(payout); return payout


@router.post("/payout-addresses/{payout_id}/primary")
def make_payout_primary(payout_id:int, db:Session=Depends(get_db), user:User=Depends(get_current_user)):
    payout=db.query(PayoutAddress).filter(PayoutAddress.id==payout_id,PayoutAddress.user_id==user.id).first()
    if not payout: raise HTTPException(404,"Payout address not found")
    db.query(PayoutAddress).filter(PayoutAddress.user_id==user.id).update({PayoutAddress.is_primary:False}); db.query(WalletConnection).filter(WalletConnection.user_id==user.id).update({WalletConnection.is_primary:False}); payout.is_primary=True; user.wallet_address=payout.address; user.wallet_chain=payout.chain; db.commit(); return {"ok":True,"payout_id":payout.id,"role":"REWARD_DESTINATION"}
