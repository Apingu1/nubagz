from decimal import Decimal
import json
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Project, Campaign, Mission, WalletConnection
from ..economy_models import OnchainRule, OnchainProof

router = APIRouter(prefix="/api/onchain", tags=["onchain"])
SUPPORTED_CHAINS = {"robinhood", "avalanche", "ethereum", "base", "arbitrum", "polygon"}


class RuleIn(BaseModel):
    mission_id: int
    chain: str = Field(default="Robinhood", max_length=32)
    rule_type: str = Field(default="TX_SUCCESS", max_length=40)
    contract_address: str | None = Field(default=None, max_length=255)
    min_amount: Decimal | None = Field(default=None, ge=0)
    token_decimals: int = Field(default=18, ge=0, le=36)


class VerifyIn(BaseModel):
    tx_hash: str | None = Field(default=None, max_length=255)


def rpc_url(chain: str) -> str | None:
    key = chain.strip().lower()
    mapping = {
        "robinhood": settings.evm_rpc_robinhood,
        "robinhood chain": settings.evm_rpc_robinhood,
        "avalanche": settings.evm_rpc_avalanche,
        "ethereum": settings.evm_rpc_ethereum,
        "base": settings.evm_rpc_base,
        "arbitrum": settings.evm_rpc_arbitrum,
        "polygon": settings.evm_rpc_polygon,
    }
    return mapping.get(key)


def rpc_call(chain: str, method: str, params: list):
    url = rpc_url(chain)
    if not url:
        raise HTTPException(503, f"{chain} RPC is not configured for this NuBagz deployment")
    try:
        response = httpx.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=10.0)
        response.raise_for_status()
        payload = response.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Could not reach {chain} RPC") from exc
    if payload.get("error"):
        raise HTTPException(502, f"RPC verification failed: {payload['error'].get('message', 'unknown error')}")
    return payload.get("result")


def serialize(rule: OnchainRule, db: Session, user_id: int | None = None):
    mission = db.get(Mission, rule.mission_id)
    campaign = db.get(Campaign, mission.campaign_id) if mission else None
    proof = db.query(OnchainProof).filter(OnchainProof.rule_id == rule.id, OnchainProof.user_id == user_id).first() if user_id else None
    return {
        "id": rule.id,
        "mission_id": rule.mission_id,
        "mission_title": mission.title if mission else "Unknown mission",
        "campaign_id": campaign.id if campaign else None,
        "campaign_title": campaign.title if campaign else None,
        "chain": rule.chain,
        "rule_type": rule.rule_type,
        "contract_address": rule.contract_address,
        "min_amount": str(rule.min_amount) if rule.min_amount is not None else None,
        "token_decimals": rule.token_decimals,
        "verified": bool(proof),
        "verified_at": proof.verified_at.isoformat() if proof else None,
    }


def creator_mission(mission_id: int, db: Session, user: User):
    mission = db.get(Mission, mission_id)
    if not mission:
        raise HTTPException(404, "Mission not found")
    campaign = db.get(Campaign, mission.campaign_id)
    project = db.get(Project, campaign.project_id) if campaign else None
    if not project or project.owner_id != user.id:
        raise HTTPException(403, "You do not manage this mission")
    return mission, campaign, project


@router.post("/rules")
def create_rule(data: RuleIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    mission, _, _ = creator_mission(data.mission_id, db, user)
    rule_type = data.rule_type.upper()
    allowed = {"TX_SUCCESS", "CONTRACT_INTERACTION", "NATIVE_BALANCE", "ERC20_BALANCE"}
    if rule_type not in allowed:
        raise HTTPException(400, "Unsupported on-chain rule type")
    chain_key = data.chain.strip().lower()
    if chain_key == "robinhood chain":
        chain_key = "robinhood"
    if chain_key not in SUPPORTED_CHAINS:
        raise HTTPException(400, "Unsupported EVM chain")
    if rule_type in {"CONTRACT_INTERACTION", "ERC20_BALANCE"} and not data.contract_address:
        raise HTTPException(400, "This rule type requires a contract address")
    if data.contract_address and not (data.contract_address.startswith("0x") and len(data.contract_address) == 42):
        raise HTTPException(400, "Contract address must be a 20-byte EVM address")
    if rule_type in {"NATIVE_BALANCE", "ERC20_BALANCE"} and data.min_amount is None:
        raise HTTPException(400, "Balance rules require a minimum amount")
    rule = db.query(OnchainRule).filter(OnchainRule.mission_id == mission.id).first()
    if rule and db.query(OnchainProof).filter(OnchainProof.rule_id == rule.id).first():
        raise HTTPException(409, "This on-chain rule is frozen because a user has already verified it")
    if not rule:
        rule = OnchainRule(mission_id=mission.id, created_by_id=user.id)
        db.add(rule)
    rule.chain = "Robinhood" if chain_key == "robinhood" else data.chain.strip().title()
    rule.rule_type = rule_type
    rule.contract_address = data.contract_address
    rule.min_amount = data.min_amount
    rule.token_decimals = data.token_decimals
    db.commit()
    db.refresh(rule)
    return serialize(rule, db, user.id)


@router.get("/rules")
def available_rules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(OnchainRule).join(Mission, Mission.id == OnchainRule.mission_id).join(Campaign, Campaign.id == Mission.campaign_id).filter(Campaign.status == "LIVE").order_by(OnchainRule.created_at.desc()).all()
    return [serialize(row, db, user.id) for row in rows]


@router.get("/mine")
def my_rules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(OnchainRule).join(Mission, Mission.id == OnchainRule.mission_id).join(Campaign, Campaign.id == Mission.campaign_id).join(Project, Project.id == Campaign.project_id).filter(Project.owner_id == user.id).order_by(OnchainRule.created_at.desc()).all()
    return [serialize(row, db, user.id) for row in rows]


@router.post("/rules/{rule_id}/verify")
def verify_rule(rule_id: int, data: VerifyIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rule = db.get(OnchainRule, rule_id)
    if not rule:
        raise HTTPException(404, "On-chain rule not found")
    mission = db.get(Mission, rule.mission_id)
    campaign = db.get(Campaign, mission.campaign_id) if mission else None
    if not campaign or campaign.status != "LIVE":
        raise HTTPException(409, "This on-chain requirement is not attached to a live Bag")
    existing = db.query(OnchainProof).filter(OnchainProof.rule_id == rule.id, OnchainProof.user_id == user.id).first()
    if existing:
        return {"verified": True, "rule_id": rule.id, "proof_id": existing.id, "message": "Already verified"}
    wallet = db.query(WalletConnection).filter(WalletConnection.user_id == user.id, WalletConnection.verified_at.isnot(None)).order_by(WalletConnection.is_primary.desc(), WalletConnection.verified_at.desc()).first()
    if not wallet:
        raise HTTPException(400, "Connect and verify an EVM wallet before using on-chain mission verification")
    address = wallet.address.lower()
    summary = {}

    if rule.rule_type in {"TX_SUCCESS", "CONTRACT_INTERACTION"}:
        if not data.tx_hash:
            raise HTTPException(400, "Transaction hash is required")
        reused = db.query(OnchainProof).filter(OnchainProof.rule_id == rule.id, OnchainProof.tx_hash == data.tx_hash).first()
        if reused:
            raise HTTPException(409, "This transaction has already been used to verify this NuBagz requirement")
        receipt = rpc_call(rule.chain, "eth_getTransactionReceipt", [data.tx_hash])
        tx = rpc_call(rule.chain, "eth_getTransactionByHash", [data.tx_hash])
        if not receipt or not tx:
            raise HTTPException(400, "Transaction was not found")
        if int(receipt.get("status", "0x0"), 16) != 1:
            raise HTTPException(400, "Transaction did not succeed")
        if (tx.get("from") or "").lower() != address:
            raise HTTPException(400, "Transaction was not sent from your verified wallet")
        if rule.rule_type == "CONTRACT_INTERACTION" and (tx.get("to") or "").lower() != (rule.contract_address or "").lower():
            raise HTTPException(400, "Transaction did not interact with the required contract")
        summary = {"status": "success", "from": tx.get("from"), "to": tx.get("to")}

    elif rule.rule_type == "NATIVE_BALANCE":
        raw = rpc_call(rule.chain, "eth_getBalance", [wallet.address, "latest"])
        balance = Decimal(int(raw, 16)) / Decimal(10**18)
        if balance < Decimal(rule.min_amount or 0):
            raise HTTPException(400, f"Wallet balance {balance} is below the required {rule.min_amount}")
        summary = {"balance": str(balance)}

    elif rule.rule_type == "ERC20_BALANCE":
        if not rule.contract_address:
            raise HTTPException(400, "Token contract is missing from this rule")
        encoded_address = wallet.address.lower().replace("0x", "").rjust(64, "0")
        call_data = "0x70a08231" + encoded_address
        raw = rpc_call(rule.chain, "eth_call", [{"to": rule.contract_address, "data": call_data}, "latest"])
        balance = Decimal(int(raw, 16)) / Decimal(10**rule.token_decimals)
        if balance < Decimal(rule.min_amount or 0):
            raise HTTPException(400, f"Token balance {balance} is below the required {rule.min_amount}")
        summary = {"balance": str(balance), "contract": rule.contract_address}

    proof = OnchainProof(rule_id=rule.id, user_id=user.id, wallet_address=wallet.address, tx_hash=data.tx_hash, proof_summary=json.dumps(summary, separators=(",", ":")))
    db.add(proof)
    db.commit()
    db.refresh(proof)
    return {"verified": True, "rule_id": rule.id, "proof_id": proof.id, "message": "On-chain requirement verified"}
