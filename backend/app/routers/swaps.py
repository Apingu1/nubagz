from datetime import datetime, UTC
from decimal import Decimal
import json
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import User, WalletConnection
from ..integration_models import SwapIntent

router = APIRouter(prefix="/api/swaps", tags=["swaps"])
SUPPORTED_CHAINS = {"avalanche", "ethereum", "base", "arbitrum", "polygon"}
CHAIN_IDS = {"avalanche": 43114, "ethereum": 1, "base": 8453, "arbitrum": 42161, "polygon": 137}


class SwapIntentIn(BaseModel):
    chain: str = Field(min_length=2, max_length=32)
    sell_asset: str = Field(min_length=1, max_length=64)
    buy_asset: str = Field(min_length=1, max_length=64)
    sell_amount: Decimal = Field(gt=0)
    max_slippage_bps: int = Field(default=100, ge=1, le=500)


def quote_active(row: SwapIntent) -> bool:
    if row.status != "QUOTED":
        return False
    if not row.quote_expires_at:
        return True
    expiry = row.quote_expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry > datetime.now(UTC)


def serialize(row: SwapIntent, wallet: WalletConnection):
    active = quote_active(row)
    display_status = "QUOTE_EXPIRED" if row.status == "QUOTED" and not active else row.status
    return {
        "id": row.id,
        "chain": row.chain,
        "sell_asset": row.sell_asset,
        "buy_asset": row.buy_asset,
        "sell_amount": str(row.sell_amount),
        "max_slippage_bps": row.max_slippage_bps,
        "status": display_status,
        "quote_active": active,
        "wallet_address": wallet.address,
        "provider": row.provider_name,
        "provider_quote_id": row.provider_quote_id,
        "quoted_buy_amount": str(row.quoted_buy_amount) if row.quoted_buy_amount is not None else None,
        "quote_expires_at": row.quote_expires_at.isoformat() if row.quote_expires_at else None,
        "transaction_payload": json.loads(row.transaction_payload) if row.transaction_payload else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "custody_model": "The provider returns an unsigned transaction for the user's verified wallet. NuBagz does not debit internal reward balances or mark broadcast/execution as successful.",
    }


def verified_wallet(db: Session, user: User) -> WalletConnection:
    wallet = db.query(WalletConnection).filter(
        WalletConnection.user_id == user.id,
        WalletConnection.verified_at.isnot(None),
    ).order_by(WalletConnection.is_primary.desc(), WalletConnection.verified_at.desc()).first()
    if not wallet:
        raise HTTPException(400, "Connect and verify an EVM wallet before creating a swap intent")
    return wallet


def valid_evm_address(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        return False
    try:
        int(value[2:], 16)
        return True
    except ValueError:
        return False


def validate_provider_transaction(transaction: dict, chain: str, wallet: WalletConnection):
    if not valid_evm_address(transaction.get("to")):
        raise HTTPException(502, "Swap provider returned an invalid transaction destination")
    data = transaction.get("data", "0x")
    if not isinstance(data, str) or not data.startswith("0x"):
        raise HTTPException(502, "Swap provider returned invalid transaction data")
    sender = transaction.get("from")
    if sender is not None and str(sender).lower() != wallet.address.lower():
        raise HTTPException(502, "Swap provider transaction sender does not match the verified wallet")
    raw_chain_id = transaction.get("chainId")
    if raw_chain_id is not None:
        try:
            chain_id = int(raw_chain_id, 0) if isinstance(raw_chain_id, str) else int(raw_chain_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(502, "Swap provider returned an invalid transaction chain") from exc
        expected = CHAIN_IDS[chain.strip().lower()]
        if chain_id != expected:
            raise HTTPException(502, "Swap provider transaction is for the wrong chain")


@router.get("/status")
def provider_status(_: User = Depends(get_current_user)):
    configured = bool(settings.swap_provider_base_url)
    return {
        "configured": configured,
        "mode": "PROVIDER_BACKED" if configured else "DRAFT_ONLY",
        "execution_model": "NuBagz requests an unsigned provider transaction for the user's verified wallet. The wallet must sign and broadcast it; NuBagz never fabricates successful execution.",
    }


@router.get("/intents")
def my_intents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(SwapIntent).filter(SwapIntent.user_id == user.id).order_by(SwapIntent.created_at.desc()).limit(100).all()
    out = []
    for row in rows:
        wallet = db.get(WalletConnection, row.wallet_connection_id)
        if wallet:
            out.append(serialize(row, wallet))
    return out


@router.post("/intents")
def create_intent(data: SwapIntentIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    chain = data.chain.strip().lower()
    if chain not in SUPPORTED_CHAINS:
        raise HTTPException(400, "Unsupported EVM chain")
    sell_asset = data.sell_asset.strip().upper()
    buy_asset = data.buy_asset.strip().upper()
    if sell_asset == buy_asset:
        raise HTTPException(400, "Sell and buy assets must be different")
    wallet = verified_wallet(db, user)
    row = SwapIntent(
        user_id=user.id,
        wallet_connection_id=wallet.id,
        chain=chain.title(),
        sell_asset=sell_asset,
        buy_asset=buy_asset,
        sell_amount=data.sell_amount,
        max_slippage_bps=data.max_slippage_bps,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize(row, wallet)


@router.post("/intents/{intent_id}/quote")
def quote_intent(intent_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(SwapIntent).filter(SwapIntent.id == intent_id, SwapIntent.user_id == user.id).first()
    if not row:
        raise HTTPException(404, "Swap intent not found")
    wallet = db.get(WalletConnection, row.wallet_connection_id)
    if not wallet or wallet.user_id != user.id or not wallet.verified_at:
        raise HTTPException(409, "The verified wallet for this swap intent is no longer available")
    if not settings.swap_provider_base_url:
        raise HTTPException(503, "Swap routing provider is not configured. The intent remains a draft and no funds were moved.")

    url = settings.swap_provider_base_url.rstrip("/") + "/quote"
    headers = {"Content-Type": "application/json"}
    if settings.swap_provider_api_key:
        headers["Authorization"] = f"Bearer {settings.swap_provider_api_key}"
    request_payload = {
        "wallet_address": wallet.address,
        "chain": row.chain,
        "sell_asset": row.sell_asset,
        "buy_asset": row.buy_asset,
        "sell_amount": str(row.sell_amount),
        "max_slippage_bps": row.max_slippage_bps,
    }
    try:
        response = httpx.post(url, json=request_payload, headers=headers, timeout=12.0)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise HTTPException(502, "Swap provider quote request failed; no NuBagz balance or wallet funds were moved") from exc

    quote_id = payload.get("quote_id")
    buy_amount = payload.get("buy_amount")
    transaction = payload.get("transaction")
    if not quote_id or buy_amount is None or not isinstance(transaction, dict):
        raise HTTPException(502, "Swap provider returned an incomplete quote")
    try:
        expires_at = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00")) if payload.get("expires_at") else None
        quoted_buy = Decimal(str(buy_amount))
    except Exception as exc:
        raise HTTPException(502, "Swap provider returned invalid quote values") from exc
    if quoted_buy <= 0:
        raise HTTPException(502, "Swap provider returned a non-positive buy amount")
    if expires_at:
        expiry = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
        if expiry <= datetime.now(UTC):
            raise HTTPException(502, "Swap provider returned an already-expired quote")
    validate_provider_transaction(transaction, row.chain, wallet)

    row.status = "QUOTED"
    row.provider_name = payload.get("provider") or "configured-provider"
    row.provider_quote_id = str(quote_id)
    row.quoted_buy_amount = quoted_buy
    row.quote_expires_at = expires_at
    row.transaction_payload = json.dumps(transaction, separators=(",", ":"))
    db.commit()
    db.refresh(row)
    return serialize(row, wallet)
