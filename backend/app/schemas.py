from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class RegisterIn(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    referral_code: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class PrivyAuthIn(BaseModel):
    identity_token: str = Field(min_length=20)
    referral_code: str | None = None


class SocialAccountSyncIn(BaseModel):
    identity_token: str = Field(min_length=20)


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    role: str
    xp: int
    bag_score: int
    streak_days: int
    referral_code: str
    wallet_address: str | None
    wallet_chain: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AuthOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SocialAccountOut(BaseModel):
    id: int
    provider: str
    provider_user_id: str
    username: str | None
    email: str | None
    display_name: str | None
    profile_picture_url: str | None
    connected_at: datetime
    last_verified_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WalletUpdate(BaseModel):
    wallet_address: str = Field(min_length=8, max_length=255)
    wallet_chain: str = Field(min_length=2, max_length=32)


class WalletChallengeIn(BaseModel):
    address: str = Field(pattern=r"^0x[a-fA-F0-9]{40}$")


class WalletVerifyIn(BaseModel):
    challenge_id: int
    address: str = Field(pattern=r"^0x[a-fA-F0-9]{40}$")
    signature: str = Field(min_length=20, max_length=1024)
    wallet_client_type: str = Field(default="unknown", max_length=64)
    connector_type: str = Field(default="unknown", max_length=64)
    chain_id: int | None = None
    make_primary: bool = True


class WalletConnectionOut(BaseModel):
    id: int
    address: str
    chain_type: str
    chain_id: int | None
    wallet_client_type: str
    connector_type: str
    wallet_type: str
    is_primary: bool
    verified_at: datetime | None
    last_connected_at: datetime
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PayoutAddressIn(BaseModel):
    address: str = Field(min_length=8, max_length=255)
    chain: str = Field(min_length=2, max_length=32)
    label: str = Field(default="Reward address", min_length=2, max_length=80)
    make_primary: bool = True


class PayoutAddressOut(BaseModel):
    id: int
    address: str
    chain: str
    label: str
    is_primary: bool
    verification_status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    symbol: str = Field(min_length=1, max_length=24)
    description: str = Field(min_length=20, max_length=5000)
    website: str | None = None
    chain: str = "Avalanche"
    logo_url: str | None = None
    treasury_address: str | None = None


class ProjectOut(BaseModel):
    id: int
    owner_id: int
    name: str
    slug: str
    symbol: str
    description: str
    website: str | None
    chain: str
    logo_url: str | None
    treasury_address: str | None
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class MissionCreate(BaseModel):
    """Legacy request shape retained only so old stored records can deserialize.

    New Bags are Challenge-only and CampaignCreate rejects non-empty missions.
    """

    title: str
    description: str = ""
    mission_type: str = "LEARN"
    verification_type: str = "PROJECT_REVIEW"
    target_url: str | None = None
    quiz_question: str | None = None
    quiz_options: list[str] | None = None
    quiz_answer: str | None = None
    xp_reward: int = 50


class MissionOut(BaseModel):
    id: int
    title: str
    description: str
    mission_type: str
    verification_type: str
    target_url: str | None
    quiz_question: str | None
    quiz_options: list[str] | None
    xp_reward: int
    position: int
    model_config = ConfigDict(from_attributes=True)


class GasSponsorshipCreate(BaseModel):
    enabled: bool = True
    chain: str = Field(min_length=2, max_length=32)
    max_native_per_claim: Decimal = Field(gt=0)
    max_unique_users: int | None = Field(default=None, gt=0, le=1_000_000)
    max_claims: int = Field(gt=0, le=1_000_000)
    max_claims_per_wallet: int = Field(default=1, gt=0, le=100)
    funded_amount: Decimal = Field(gt=0)
    funding_reference: str = Field(min_length=4, max_length=255)
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def validate_sponsorship(self):
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValueError("Gas Pass end time must be after its start time")
        return self


class ChallengeCreate(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    description: str = ""
    category: str = "BAG_WORK"
    provider: str | None = None
    action: str | None = None
    verification_type: str = "PROJECT_REVIEW"
    target_url: str | None = None
    target_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    xp_reward: int = Field(default=50, ge=0, le=100000)
    gas_sponsorship: GasSponsorshipCreate | None = None

    @model_validator(mode="after")
    def validate_challenge(self):
        self.category = self.category.upper()
        self.verification_type = self.verification_type.upper()
        if self.provider:
            self.provider = self.provider.upper()
        if self.action:
            self.action = self.action.upper()

        allowed_categories = {"SOCIAL", "COMMUNITY", "CONTENT", "ONCHAIN", "BAG_WORK", "LEARN", "CUSTOM"}
        if self.category not in allowed_categories:
            raise ValueError("Unsupported Bag Work category")

        # X work is always objectively verified against the connected X identity.
        if self.category == "SOCIAL":
            if self.provider != "X":
                raise ValueError("X is the only social challenge provider enabled in this release")
            requirements = {
                "POST": "required_text",
                "MENTION": "required_mention",
                "HASHTAG": "required_hashtag",
                "LINK": "required_link",
            }
            if self.action not in requirements:
                raise ValueError("Free X proof actions are POST, MENTION, HASHTAG and LINK")
            key = requirements[self.action]
            raw = str(self.config.get(key) or "").strip()
            if not raw:
                raise ValueError(f"{self.action.title()} X challenges require a public-post requirement")
            if len(raw) > 500:
                raise ValueError("X public-post requirements must be 500 characters or fewer")
            if self.action == "MENTION":
                raw = "@" + raw.lstrip("@")
            elif self.action == "HASHTAG":
                raw = "#" + raw.lstrip("#")
            elif self.action == "LINK":
                candidate = raw.lower()
                if not (candidate.startswith("https://") or candidate.startswith("http://")):
                    raise ValueError("Link X challenges require a full http:// or https:// URL")
            self.config = {**self.config, key: raw}
            self.verification_type = "AUTO"
            self.target_url = None
            self.target_id = None

        if self.category == "ONCHAIN" and self.verification_type == "AUTO":
            supported = {"avalanche", "ethereum", "base", "arbitrum", "polygon"}
            chain = str(self.config.get("chain") or "").strip()
            target = str(self.config.get("target_address") or self.target_id or "").strip()
            if chain.lower() not in supported:
                raise ValueError("Automatic on-chain verification supports Avalanche, Ethereum, Base, Arbitrum and Polygon")
            if not (target.startswith("0x") and len(target) == 42):
                raise ValueError("Automatic on-chain Bag Work requires a 20-byte EVM target address")
            try:
                int(target[2:], 16)
            except ValueError as exc:
                raise ValueError("Automatic on-chain Bag Work requires a valid hexadecimal EVM target address") from exc
            calldata = str(self.config.get("calldata") or "0x").strip()
            if not calldata.startswith("0x"):
                raise ValueError("On-chain transaction calldata must begin with 0x")
            try:
                if len(calldata) > 2:
                    int(calldata[2:], 16)
            except ValueError as exc:
                raise ValueError("On-chain transaction calldata must be hexadecimal") from exc
            try:
                value_wei = int(str(self.config.get("value_wei") or "0"), 0)
            except (TypeError, ValueError) as exc:
                raise ValueError("On-chain transaction value must be a non-negative wei integer") from exc
            if value_wei < 0:
                raise ValueError("On-chain transaction value must be a non-negative wei integer")
            self.target_id = target
            self.config = {
                **self.config,
                "target_address": target,
                "chain": chain,
                "calldata": calldata,
                "value_wei": str(value_wei),
            }

        if self.gas_sponsorship:
            if self.category != "ONCHAIN":
                raise ValueError("Gas Pass can only be attached to ONCHAIN Bag Work")
            target = str(self.config.get("target_address") or self.target_id or "").strip()
            if not target:
                raise ValueError("Sponsored on-chain work requires a target contract/address")
            self.config = {**self.config, "target_address": target, "chain": self.gas_sponsorship.chain}

        if self.verification_type not in {"AUTO", "PROJECT_REVIEW", "QUIZ"}:
            raise ValueError("Verification must be automatic, quiz-based, or project-reviewed evidence")
        if self.verification_type == "AUTO" and self.category not in {"SOCIAL", "ONCHAIN"}:
            raise ValueError("Automatic verification is only configured for X social work and supported on-chain work")
        if self.verification_type == "QUIZ" and not str(self.config.get("answer") or "").strip():
            raise ValueError("Quiz challenges require a correct answer in config")
        return self


class ChallengeOut(BaseModel):
    id: int
    campaign_id: int
    title: str
    description: str
    category: str
    provider: str | None
    action: str | None
    verification_type: str
    target_url: str | None
    target_id: str | None
    config: dict[str, Any]
    xp_reward: int
    position: int
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CampaignCreate(BaseModel):
    project_id: int
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=20, max_length=5000)
    category: str = "DISCOVER"
    difficulty: str = "EASY"
    reward_asset: str = Field(min_length=1, max_length=24)
    funding_type: str = "TOKEN"
    token_allocation: Decimal = Field(gt=0)
    gross_reward_per_user: Decimal = Field(gt=0)
    user_share_pct: Decimal = Decimal("80")
    nubagz_share_pct: Decimal = Decimal("15")
    referral_share_pct: Decimal = Decimal("5")
    max_users: int = Field(gt=0, le=1_000_000)
    estimated_value_gbp: Decimal | None = None
    missions: list[MissionCreate] = Field(default_factory=list)
    challenges: list[ChallengeCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_bag(self):
        if self.user_share_pct + self.nubagz_share_pct + self.referral_share_pct != Decimal("100"):
            raise ValueError("Reward shares must total 100%")
        if self.gross_reward_per_user * self.max_users > self.token_allocation:
            raise ValueError("Token allocation must cover maximum gross rewards")
        if self.missions:
            raise ValueError("Legacy Missions are retired. Create Bag Work with unified Challenges instead")
        if not self.challenges:
            raise ValueError("A Bag requires at least one unified Bag Work Challenge")
        return self


class CampaignOut(BaseModel):
    id: int
    project_id: int
    title: str
    description: str
    category: str
    difficulty: str
    reward_asset: str
    funding_type: str
    token_allocation: Decimal
    gross_reward_per_user: Decimal
    user_share_pct: Decimal
    nubagz_share_pct: Decimal
    referral_share_pct: Decimal
    max_users: int
    status: str
    featured: bool
    estimated_value_gbp: Decimal | None
    created_at: datetime
    missions: list[MissionOut] = []
    challenges: list[ChallengeOut] = []
    project: ProjectOut | None = None
    enrolled_count: int = 0
    completed_count: int = 0
    model_config = ConfigDict(from_attributes=True)


class MissionCompleteIn(BaseModel):
    answer: str | None = None


class ChallengeCompleteIn(BaseModel):
    answer: str | None = None
    evidence: str | None = None


class ChallengeDecisionIn(BaseModel):
    status: str


class RewardBalance(BaseModel):
    asset_symbol: str
    amount: Decimal


class WithdrawalIn(BaseModel):
    asset_symbol: str
    amount: Decimal = Field(gt=0)
    chain: str
    wallet_address: str = Field(min_length=8, max_length=255)


class DashboardOut(BaseModel):
    lifetime_assets: int
    active_bagz: int
    completed_bagz: int
    xp: int
    bag_score: int
    streak_days: int
    balances: list[RewardBalance]
    recent_activity: list[dict[str, Any]]


class AdminDecision(BaseModel):
    status: str
