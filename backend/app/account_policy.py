from fastapi import HTTPException

from .models import ACCOUNT_STATES, User

AUTHENTICATE = "AUTHENTICATE"
EARN_REWARDS = "EARN_REWARDS"
INTERACTIVE_ONCHAIN = "INTERACTIVE_ONCHAIN"
SWAP = "SWAP"

CAPABILITIES_BY_STATE: dict[str, set[str]] = {
    "ACTIVE": {AUTHENTICATE, EARN_REWARDS, INTERACTIVE_ONCHAIN, SWAP},
    # UNDER_REVIEW is intentionally not guilt-by-signal. The account remains
    # usable while later Trust/reward-hold layers can route higher-risk value.
    "UNDER_REVIEW": {AUTHENTICATE, EARN_REWARDS, INTERACTIVE_ONCHAIN, SWAP},
    # RESTRICTED accounts keep access to their history/support surfaces but may
    # not initiate new reward-bearing or interactive value actions.
    "RESTRICTED": {AUTHENTICATE},
    "SUSPENDED": set(),
    "DISQUALIFIED": set(),
}


def normalized_account_state(user: User) -> str:
    state = str(user.account_state or "ACTIVE").upper()
    if state not in ACCOUNT_STATES:
        # Unknown persisted states fail closed rather than silently becoming ACTIVE.
        return "SUSPENDED"
    if not user.is_active:
        return "SUSPENDED"
    return state


def allows(user: User, capability: str) -> bool:
    return capability in CAPABILITIES_BY_STATE.get(normalized_account_state(user), set())


def require_capability(user: User, capability: str, detail: str) -> None:
    if not allows(user, capability):
        raise HTTPException(status_code=403, detail=detail)
