from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..integration_models import SwapIntent
from ..models import User, WalletConnection
from .onchain import rpc_call

router = APIRouter(prefix="/api/swaps", tags=["swaps"])

NATIVE_TOKEN = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

CHAINS = {
    "robinhood": {
        "name": "Robinhood",
        "display_name": "Robinhood Chain",
        "chain_id": 4663,
        "native_symbol": "ETH",
        "rpc_url": "https://rpc.mainnet.chain.robinhood.com",
        "explorer": "https://robinhoodchain.blockscout.com",
        "dexscreener": "robinhood",
        "wrapped_native": "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73",
        "tokens": [
            {"address": NATIVE_TOKEN, "symbol": "ETH", "name": "Ether", "decimals": 18, "kind": "native"},
            {"address": "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73", "symbol": "WETH", "name": "Wrapped Ether", "decimals": 18, "kind": "erc20"},
            {"address": "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168", "symbol": "USDG", "name": "Global Dollar", "decimals": 6, "kind": "erc20"},
        ],
    },
    "avalanche": {"name": "Avalanche", "display_name": "Avalanche", "chain_id": 43114, "native_symbol": "AVAX", "explorer": "https://snowtrace.io", "dexscreener": "avalanche", "wrapped_native": None, "tokens": [{"address": NATIVE_TOKEN, "symbol": "AVAX", "name": "Avalanche", "decimals": 18, "kind": "native"}]},
    "ethereum": {"name": "Ethereum", "display_name": "Ethereum", "chain_id": 1, "native_symbol": "ETH", "explorer": "https://etherscan.io", "dexscreener": "ethereum", "wrapped_native": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "tokens": [{"address": NATIVE_TOKEN, "symbol": "ETH", "name": "Ether", "decimals": 18, "kind": "native"}]},
    "base": {"name": "Base", "display_name": "Base", "chain_id": 8453, "native_symbol": "ETH", "explorer": "https://basescan.org", "dexscreener": "base", "wrapped_native": "0x4200000000000000000000000000000000000006", "tokens": [{"address": NATIVE_TOKEN, "symbol": "ETH", "name": "Ether", "decimals": 18, "kind": "native"}]},
    "arbitrum": {"name": "Arbitrum", "display_name": "Arbitrum", "chain_id": 42161, "native_symbol": "ETH", "explorer": "https://arbiscan.io", "dexscreener": "arbitrum", "wrapped_native": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "tokens": [{"address": NATIVE_TOKEN, "symbol": "ETH", "name": "Ether", "decimals": 18, "kind": "native"}]},
    "polygon": {"name": "Polygon", "display_name": "Polygon", "chain_id": 137, "native_symbol": "POL", "explorer": "https://polygonscan.com", "dexscreener": "polygon", "wrapped_native": None, "tokens": [{"address": NATIVE_TOKEN, "symbol": "POL", "name": "POL", "decimals": 18, "kind": "native"}]},
}


class QuoteIn(BaseModel):
    chain: str = Field(default="Robinhood", min_length=2, max_length=32)
    sell_token: str = Field(min_length=3, max_length=64)
    buy_token: str = Field(min_length=3, max_length=64)
    sell_amount: str = Field(min_length=1, max_length=90)
    slippage_bps: int = Field(default=100, ge=1, le=500)


class ConfirmIn(BaseModel):
    session_id: int
    tx_hash: str = Field(min_length=66, max_length=66)


def _valid_evm_address(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        return False
    try:
        int(value[2:], 16)
        return True
    except ValueError:
        return False


def _valid_tx_hash(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        return False
    try:
        int(value[2:], 16)
        return True
    except ValueError:
        return False


def _chain(value: str):
    key = value.strip().lower()
    if key == "robinhood chain":
        key = "robinhood"
    if key not in CHAINS:
        raise HTTPException(400, "Unsupported EVM chain")
    return key, CHAINS[key]


def _normalise_token(value: str, chain: dict) -> str:
    candidate = value.strip()
    if candidate.lower() in {"native", chain["native_symbol"].lower(), NATIVE_TOKEN, ZERO_ADDRESS}:
        return NATIVE_TOKEN
    if not _valid_evm_address(candidate):
        raise HTTPException(400, "Tokens must be the native asset or a valid 20-byte EVM contract address")
    return candidate


def _verified_wallet(db: Session, user: User) -> WalletConnection:
    wallet = db.query(WalletConnection).filter(
        WalletConnection.user_id == user.id,
        WalletConnection.verified_at.isnot(None),
    ).order_by(WalletConnection.is_primary.desc(), WalletConnection.verified_at.desc()).first()
    if not wallet:
        raise HTTPException(400, "Connect and verify an EVM wallet before swapping")
    return wallet


def _decode_abi_string(raw: str | None) -> str | None:
    if not raw or raw == "0x":
        return None
    data = raw[2:] if raw.startswith("0x") else raw
    try:
        if len(data) == 64:
            return bytes.fromhex(data).rstrip(b"\x00").decode("utf-8", errors="ignore") or None
        if len(data) >= 128:
            offset = int(data[:64], 16) * 2
            length = int(data[offset:offset + 64], 16)
            start = offset + 64
            return bytes.fromhex(data[start:start + length * 2]).decode("utf-8", errors="ignore") or None
    except Exception:
        return None
    return None


def _token_metadata(chain_key: str, token: str) -> dict:
    chain = CHAINS[chain_key]
    if token.lower() == NATIVE_TOKEN:
        return {"address": NATIVE_TOKEN, "symbol": chain["native_symbol"], "name": chain["native_symbol"], "decimals": 18, "kind": "native"}
    decimals_raw = rpc_call(chain["name"], "eth_call", [{"to": token, "data": "0x313ce567"}, "latest"])
    symbol_raw = rpc_call(chain["name"], "eth_call", [{"to": token, "data": "0x95d89b41"}, "latest"])
    name_raw = rpc_call(chain["name"], "eth_call", [{"to": token, "data": "0x06fdde03"}, "latest"])
    try:
        decimals = int(decimals_raw, 16)
    except Exception as exc:
        raise HTTPException(400, "Could not read token decimals from this contract") from exc
    if decimals < 0 or decimals > 36:
        raise HTTPException(400, "Token contract returned unsupported decimals")
    symbol = _decode_abi_string(symbol_raw) or token[:8]
    name = _decode_abi_string(name_raw) or symbol
    return {"address": token, "symbol": symbol, "name": name, "decimals": decimals, "kind": "erc20"}


def _validate_transaction(transaction: dict, chain: dict, wallet: WalletConnection):
    if not isinstance(transaction, dict) or not _valid_evm_address(transaction.get("to")):
        raise HTTPException(502, "Swap router returned an invalid transaction destination")
    data = transaction.get("data", "0x")
    if not isinstance(data, str) or not data.startswith("0x"):
        raise HTTPException(502, "Swap router returned invalid transaction data")
    sender = transaction.get("from")
    if sender and str(sender).lower() != wallet.address.lower():
        raise HTTPException(502, "Swap router transaction sender does not match the verified wallet")
    raw_chain = transaction.get("chainId")
    if raw_chain is not None:
        try:
            chain_id = int(raw_chain, 0) if isinstance(raw_chain, str) else int(raw_chain)
        except (TypeError, ValueError) as exc:
            raise HTTPException(502, "Swap router returned an invalid chain ID") from exc
        if chain_id != chain["chain_id"]:
            raise HTTPException(502, "Swap router returned a transaction for the wrong chain")


def _route_sources_0x(payload: dict) -> list[str]:
    seen = []
    for fill in (payload.get("route") or {}).get("fills") or []:
        source = str(fill.get("source") or "").strip()
        if source and source not in seen:
            seen.append(source)
    return seen


def _fee_amount_0x(payload: dict):
    fees = payload.get("fees") or {}
    own = fees.get("integratorFee") or {}
    if own.get("amount") is not None:
        return str(own.get("amount"))
    many = fees.get("integratorFees") or []
    amounts = [Decimal(str(x.get("amount"))) for x in many if x.get("amount") is not None]
    return str(sum(amounts, Decimal("0"))) if amounts else None


def _quote_0x(chain: dict, sell_token: str, buy_token: str, sell_amount: str, slippage_bps: int, wallet: WalletConnection) -> dict:
    if not settings.zerox_api_key or not settings.nubagz_swap_fee_recipient:
        raise RuntimeError("0x not configured")
    if not _valid_evm_address(settings.nubagz_swap_fee_recipient):
        raise RuntimeError("NuBagz 0x fee recipient is invalid")
    params = {
        "chainId": chain["chain_id"],
        "sellToken": sell_token,
        "buyToken": buy_token,
        "sellAmount": sell_amount,
        "taker": wallet.address,
        "slippageBps": slippage_bps,
        "swapFeeRecipient": settings.nubagz_swap_fee_recipient,
        "swapFeeBps": settings.swap_fee_bps,
        "swapFeeToken": sell_token,
    }
    response = httpx.get(
        "https://api.0x.org/swap/allowance-holder/quote",
        params=params,
        headers={"0x-api-key": settings.zerox_api_key, "0x-version": "v2"},
        timeout=12.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("liquidityAvailable", True):
        raise RuntimeError("0x found no executable liquidity")
    transaction = payload.get("transaction") or {}
    _validate_transaction(transaction, chain, wallet)
    issues = payload.get("issues") or {}
    allowance = issues.get("allowance") or {}
    balance = issues.get("balance") or {}
    if balance.get("actual") is not None and balance.get("expected") is not None:
        if int(balance["actual"]) < int(balance["expected"]):
            raise RuntimeError("Verified wallet has insufficient sell-token balance")
    spender = allowance.get("spender") or payload.get("allowanceTarget")
    return {
        "provider": "0x",
        "provider_quote_id": str(payload.get("zid") or ""),
        "buy_amount": str(payload.get("buyAmount")),
        "min_buy_amount": str(payload.get("minBuyAmount") or payload.get("buyAmount")),
        "allowance_target": spender,
        "allowance_actual": str(allowance.get("actual")) if allowance.get("actual") is not None else None,
        "requires_approval": bool(allowance) and sell_token.lower() != NATIVE_TOKEN,
        "transaction": transaction,
        "sources": _route_sources_0x(payload),
        "network_fee_native": str(payload.get("totalNetworkFee")) if payload.get("totalNetworkFee") is not None else None,
        "nubagz_fee_amount": _fee_amount_0x(payload),
        "provider_fees": payload.get("fees") or {},
        "token_metadata": payload.get("tokenMetadata") or {},
    }


def _lifi_token(token: str) -> str:
    return ZERO_ADDRESS if token.lower() == NATIVE_TOKEN else token


def _quote_lifi(chain: dict, sell_token: str, buy_token: str, sell_amount: str, slippage_bps: int, wallet: WalletConnection) -> dict:
    if not settings.lifi_api_key or not settings.lifi_integrator:
        raise RuntimeError("LI.FI not configured")
    params = {
        "fromChain": chain["chain_id"],
        "toChain": chain["chain_id"],
        "fromToken": _lifi_token(sell_token),
        "toToken": _lifi_token(buy_token),
        "fromAddress": wallet.address,
        "toAddress": wallet.address,
        "fromAmount": sell_amount,
        "slippage": str(Decimal(slippage_bps) / Decimal(10000)),
        "order": "CHEAPEST",
        "integrator": settings.lifi_integrator,
        "fee": str(Decimal(settings.swap_fee_bps) / Decimal(10000)),
    }
    response = httpx.get(
        "https://li.quest/v1/quote",
        params=params,
        headers={"x-lifi-api-key": settings.lifi_api_key},
        timeout=12.0,
    )
    response.raise_for_status()
    payload = response.json()
    estimate = payload.get("estimate") or {}
    transaction = payload.get("transactionRequest") or {}
    _validate_transaction(transaction, chain, wallet)
    gas_costs = estimate.get("gasCosts") or []
    network_fee_usd = sum((Decimal(str(x.get("amountUSD") or "0")) for x in gas_costs), Decimal("0"))
    fee_costs = estimate.get("feeCosts") or []
    own_fee = None
    for item in fee_costs:
        name = str(item.get("name") or item.get("type") or "").lower()
        if "integrator" in name or "fee" in name:
            own_fee = item.get("amount")
            break
    return {
        "provider": "LI.FI",
        "provider_quote_id": str(payload.get("id") or ""),
        "buy_amount": str(estimate.get("toAmount")),
        "min_buy_amount": str(estimate.get("toAmountMin") or estimate.get("toAmount")),
        "allowance_target": estimate.get("approvalAddress"),
        "allowance_actual": None,
        "requires_approval": bool(estimate.get("approvalAddress")) and sell_token.lower() != NATIVE_TOKEN,
        "transaction": transaction,
        "sources": [str((payload.get("toolDetails") or {}).get("name") or payload.get("tool") or "LI.FI")],
        "network_fee_native": None,
        "network_fee_usd": str(network_fee_usd),
        "nubagz_fee_amount": str(own_fee) if own_fee is not None else None,
        "provider_fees": {"feeCosts": fee_costs},
        "token_metadata": {},
    }


def _store_route(db: Session, user: User, wallet: WalletConnection, chain: dict, data: QuoteIn, sell_token: str, buy_token: str, route: dict) -> int:
    row = SwapIntent(
        user_id=user.id,
        wallet_connection_id=wallet.id,
        chain=chain["name"],
        sell_asset=sell_token,
        buy_asset=buy_token,
        sell_amount=Decimal(data.sell_amount),
        max_slippage_bps=data.slippage_bps,
        status="QUOTED",
        provider_name=route["provider"],
        provider_quote_id=route.get("provider_quote_id") or None,
        quoted_buy_amount=Decimal(route["buy_amount"]),
        quote_expires_at=datetime.now(UTC) + timedelta(seconds=90),
        transaction_payload=json.dumps(route, separators=(",", ":")),
    )
    db.add(row)
    db.flush()
    return row.id


def _session_payload(row: SwapIntent, wallet: WalletConnection):
    details = json.loads(row.transaction_payload) if row.transaction_payload else {}
    receipt = details.get("receipt") or {}
    return {
        "session_id": row.id,
        "chain": row.chain,
        "provider": row.provider_name,
        "status": row.status,
        "sell_token": row.sell_asset,
        "buy_token": row.buy_asset,
        "sell_amount": str(row.sell_amount),
        "quoted_buy_amount": str(row.quoted_buy_amount) if row.quoted_buy_amount is not None else None,
        "wallet_address": wallet.address,
        "tx_hash": details.get("tx_hash"),
        "actual_buy_amount": receipt.get("actual_buy_amount"),
        "block_number": receipt.get("block_number"),
        "gas_used": receipt.get("gas_used"),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _actual_erc20_received(receipt: dict, buy_token: str, wallet_address: str) -> str | None:
    if buy_token.lower() == NATIVE_TOKEN:
        return None
    target_topic = "0x" + wallet_address.lower().replace("0x", "").rjust(64, "0")
    total = 0
    for log in receipt.get("logs") or []:
        if str(log.get("address") or "").lower() != buy_token.lower():
            continue
        topics = log.get("topics") or []
        if len(topics) < 3 or str(topics[0]).lower() != TRANSFER_TOPIC or str(topics[2]).lower() != target_topic:
            continue
        try:
            total += int(log.get("data") or "0x0", 16)
        except ValueError:
            continue
    return str(total) if total else None


@router.get("/config")
def swap_config(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    wallet = db.query(WalletConnection).filter(
        WalletConnection.user_id == user.id,
        WalletConnection.verified_at.isnot(None),
    ).order_by(WalletConnection.is_primary.desc(), WalletConnection.verified_at.desc()).first()
    providers = {
        "0x": bool(settings.zerox_api_key and settings.nubagz_swap_fee_recipient and _valid_evm_address(settings.nubagz_swap_fee_recipient)),
        "LI.FI": bool(settings.lifi_api_key and settings.lifi_integrator),
    }
    return {
        "primary_chain": "Robinhood",
        "fee_bps": settings.swap_fee_bps,
        "fee_percent": str(Decimal(settings.swap_fee_bps) / Decimal(100)),
        "wallet_address": wallet.address if wallet else None,
        "providers": providers,
        "ready": any(providers.values()),
        "chains": [{**value, "key": key} for key, value in CHAINS.items()],
        "execution_model": "Quotes contain NuBagz's disclosed integrator fee. The verified connected wallet signs approvals and swaps directly; NuBagz never has custody of keys or swap funds.",
    }


@router.get("/token")
def token_metadata(
    chain: str = Query(default="Robinhood"),
    address: str = Query(...),
    _: User = Depends(get_current_user),
):
    key, chain_spec = _chain(chain)
    token = _normalise_token(address, chain_spec)
    return _token_metadata(key, token)


@router.get("/token-search")
def token_search(
    chain: str = Query(default="Robinhood"),
    q: str = Query(min_length=1, max_length=100),
    _: User = Depends(get_current_user),
):
    key, chain_spec = _chain(chain)
    text = q.strip()
    if _valid_evm_address(text):
        try:
            return [_token_metadata(key, text)]
        except HTTPException:
            return []
    results = list(chain_spec["tokens"])
    try:
        response = httpx.get("https://api.dexscreener.com/latest/dex/search", params={"q": text}, timeout=8.0)
        response.raise_for_status()
        pairs = response.json().get("pairs") or []
    except Exception:
        pairs = []
    addresses = []
    fallback = {}
    for pair in pairs:
        if str(pair.get("chainId") or "").lower() != chain_spec["dexscreener"]:
            continue
        for item in (pair.get("baseToken") or {}, pair.get("quoteToken") or {}):
            address = item.get("address")
            if _valid_evm_address(address) and address.lower() not in {x.lower() for x in addresses}:
                addresses.append(address)
                fallback[address.lower()] = item
        if len(addresses) >= 8:
            break
    for address in addresses:
        if any(str(x.get("address")).lower() == address.lower() for x in results):
            continue
        try:
            results.append(_token_metadata(key, address))
        except HTTPException:
            item = fallback.get(address.lower()) or {}
            results.append({"address": address, "symbol": item.get("symbol") or address[:8], "name": item.get("name") or item.get("symbol") or address[:8], "decimals": 18, "kind": "erc20", "metadata_estimated": True})
    query_lower = text.lower()
    results.sort(key=lambda x: 0 if query_lower in str(x.get("symbol") or "").lower() else 1)
    return results[:12]


@router.get("/market")
def market_data(
    chain: str = Query(default="Robinhood"),
    token: str = Query(...),
    _: User = Depends(get_current_user),
):
    _, chain_spec = _chain(chain)
    target = _normalise_token(token, chain_spec)
    if target.lower() == NATIVE_TOKEN and chain_spec.get("wrapped_native"):
        target = chain_spec["wrapped_native"]
    if target.lower() == NATIVE_TOKEN:
        return {"available": False, "signals": ["NO_DEXSCREENER_PAIR"]}
    try:
        response = httpx.get("https://api.dexscreener.com/latest/dex/search", params={"q": target}, timeout=8.0)
        response.raise_for_status()
        pairs = [p for p in (response.json().get("pairs") or []) if str(p.get("chainId") or "").lower() == chain_spec["dexscreener"]]
    except Exception:
        pairs = []
    if not pairs:
        return {"available": False, "signals": ["NO_DEXSCREENER_PAIR"]}
    pair = max(pairs, key=lambda p: Decimal(str(((p.get("liquidity") or {}).get("usd") or 0))))
    liquidity = Decimal(str((pair.get("liquidity") or {}).get("usd") or 0))
    created = pair.get("pairCreatedAt")
    age_days = None
    if created:
        try:
            age_days = max(0, (datetime.now(UTC) - datetime.fromtimestamp(int(created) / 1000, tz=UTC)).days)
        except Exception:
            age_days = None
    signals = []
    if liquidity < Decimal("10000"):
        signals.append("LOW_LIQUIDITY")
    if age_days is not None and age_days < 7:
        signals.append("NEW_PAIR")
    if not signals:
        signals.append("NO_BASIC_MARKET_WARNING")
    pair_address = pair.get("pairAddress")
    link = f"https://dexscreener.com/{chain_spec['dexscreener']}/{pair_address}" if pair_address else None
    return {
        "available": True,
        "pair_address": pair_address,
        "dex": pair.get("dexId"),
        "url": link,
        "embed_url": f"{link}?embed=1&info=0&theme=dark&trades=0" if link else None,
        "price_usd": pair.get("priceUsd"),
        "liquidity_usd": str(liquidity),
        "volume_24h_usd": str((pair.get("volume") or {}).get("h24") or 0),
        "price_change_24h": (pair.get("priceChange") or {}).get("h24"),
        "fdv": pair.get("fdv"),
        "market_cap": pair.get("marketCap"),
        "pair_age_days": age_days,
        "base_token": pair.get("baseToken"),
        "quote_token": pair.get("quoteToken"),
        "signals": signals,
        "disclaimer": "Market signals are informational and do not mean a token or pool is safe.",
    }


@router.post("/quote")
def quote_routes(
    data: QuoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _, chain = _chain(data.chain)
    wallet = _verified_wallet(db, user)
    sell_token = _normalise_token(data.sell_token, chain)
    buy_token = _normalise_token(data.buy_token, chain)
    if sell_token.lower() == buy_token.lower():
        raise HTTPException(400, "Sell and buy tokens must be different")
    try:
        amount = int(data.sell_amount)
    except ValueError as exc:
        raise HTTPException(400, "Sell amount must be an integer in token base units") from exc
    if amount <= 0:
        raise HTTPException(400, "Sell amount must be greater than zero")

    routes = []
    errors = {}
    providers = [
        ("0x", lambda: _quote_0x(chain, sell_token, buy_token, data.sell_amount, data.slippage_bps, wallet)),
        ("LI.FI", lambda: _quote_lifi(chain, sell_token, buy_token, data.sell_amount, data.slippage_bps, wallet)),
    ]
    for name, getter in providers:
        try:
            route = getter()
            if not route.get("buy_amount") or int(route["buy_amount"]) <= 0:
                raise RuntimeError("router returned no positive output")
            route["session_id"] = _store_route(db, user, wallet, chain, data, sell_token, buy_token, route)
            route["nubagz_fee_bps"] = settings.swap_fee_bps
            routes.append(route)
        except Exception as exc:
            errors[name] = str(exc)[:240]
    if not routes:
        db.rollback()
        raise HTTPException(503, "No executable fee-enabled swap route is currently available. Configure 0x and/or LI.FI integration credentials and the NuBagz fee recipient.")
    routes.sort(key=lambda x: int(x["buy_amount"]), reverse=True)
    db.commit()
    routes[0]["recommended"] = True
    for route in routes[1:]:
        route["recommended"] = False
    return {
        "chain": chain["name"],
        "chain_id": chain["chain_id"],
        "wallet_address": wallet.address,
        "sell_token": sell_token,
        "buy_token": buy_token,
        "sell_amount": data.sell_amount,
        "slippage_bps": data.slippage_bps,
        "nubagz_fee_bps": settings.swap_fee_bps,
        "routes": routes,
        "provider_errors": errors,
        "quote_expires_seconds": 90,
    }


@router.post("/confirm")
def confirm_swap(
    data: ConfirmIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _valid_tx_hash(data.tx_hash):
        raise HTTPException(400, "Invalid transaction hash")
    row = db.query(SwapIntent).filter(SwapIntent.id == data.session_id, SwapIntent.user_id == user.id).first()
    if not row:
        raise HTTPException(404, "Swap session not found")
    wallet = db.get(WalletConnection, row.wallet_connection_id)
    if not wallet or wallet.user_id != user.id or not wallet.verified_at:
        raise HTTPException(409, "The verified wallet for this swap is no longer available")
    details = json.loads(row.transaction_payload) if row.transaction_payload else {}
    expected = details.get("transaction") or {}
    receipt = rpc_call(row.chain, "eth_getTransactionReceipt", [data.tx_hash])
    tx = rpc_call(row.chain, "eth_getTransactionByHash", [data.tx_hash])
    if not tx:
        raise HTTPException(400, "Transaction was not found on the selected chain")
    if str(tx.get("from") or "").lower() != wallet.address.lower():
        raise HTTPException(400, "Swap transaction was not sent from the verified wallet")
    if str(tx.get("to") or "").lower() != str(expected.get("to") or "").lower():
        raise HTTPException(400, "Swap transaction destination does not match the selected executable route")
    details["tx_hash"] = data.tx_hash
    if not receipt:
        row.status = "SUBMITTED"
        row.transaction_payload = json.dumps(details, separators=(",", ":"))
        db.commit()
        return {"status": "SUBMITTED", "tx_hash": data.tx_hash, "confirmed": False}
    success = int(receipt.get("status", "0x0"), 16) == 1
    actual = _actual_erc20_received(receipt, row.buy_asset, wallet.address) if success else None
    details["receipt"] = {
        "status": "CONFIRMED" if success else "FAILED",
        "block_number": str(int(receipt.get("blockNumber", "0x0"), 16)),
        "gas_used": str(int(receipt.get("gasUsed", "0x0"), 16)),
        "effective_gas_price": str(int(receipt.get("effectiveGasPrice", "0x0"), 16)) if receipt.get("effectiveGasPrice") else None,
        "actual_buy_amount": actual,
    }
    row.status = "CONFIRMED" if success else "FAILED"
    row.transaction_payload = json.dumps(details, separators=(",", ":"))
    db.commit()
    _, chain = _chain(row.chain)
    return {
        "status": row.status,
        "confirmed": success,
        "tx_hash": data.tx_hash,
        "actual_buy_amount": actual,
        "quoted_buy_amount": str(row.quoted_buy_amount) if row.quoted_buy_amount is not None else None,
        "block_number": details["receipt"]["block_number"],
        "gas_used": details["receipt"]["gas_used"],
        "explorer_url": f"{chain['explorer']}/tx/{data.tx_hash}",
    }


@router.get("/history")
def swap_history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(SwapIntent).filter(
        SwapIntent.user_id == user.id,
        SwapIntent.status.in_(["SUBMITTED", "CONFIRMED", "FAILED"]),
    ).order_by(SwapIntent.updated_at.desc()).limit(50).all()
    out = []
    for row in rows:
        wallet = db.get(WalletConnection, row.wallet_connection_id)
        if wallet:
            payload = _session_payload(row, wallet)
            _, chain = _chain(row.chain)
            if payload.get("tx_hash"):
                payload["explorer_url"] = f"{chain['explorer']}/tx/{payload['tx_hash']}"
            out.append(payload)
    return out
