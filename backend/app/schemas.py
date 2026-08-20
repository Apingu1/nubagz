from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, EmailStr, Field, ConfigDict, model_validator

class RegisterIn(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    referral_code: str | None = None

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id:int; email:str; username:str; role:str; xp:int; bag_score:int; streak_days:int; referral_code:str
    wallet_address:str|None; wallet_chain:str|None; created_at:datetime
    model_config=ConfigDict(from_attributes=True)

class AuthOut(BaseModel):
    access_token:str; token_type:str="bearer"; user:UserOut

class WalletUpdate(BaseModel):
    wallet_address:str=Field(min_length=8,max_length=255); wallet_chain:str=Field(min_length=2,max_length=32)

class WalletChallengeIn(BaseModel):
    address:str=Field(pattern=r"^0x[a-fA-F0-9]{40}$")

class WalletVerifyIn(BaseModel):
    challenge_id:int; address:str=Field(pattern=r"^0x[a-fA-F0-9]{40}$"); signature:str=Field(min_length=20,max_length=1024)
    wallet_client_type:str=Field(default="unknown",max_length=64); connector_type:str=Field(default="unknown",max_length=64)
    chain_id:int|None=None; make_primary:bool=True

class WalletConnectionOut(BaseModel):
    id:int; address:str; chain_type:str; chain_id:int|None; wallet_client_type:str; connector_type:str; wallet_type:str
    is_primary:bool; verified_at:datetime|None; last_connected_at:datetime; created_at:datetime
    model_config=ConfigDict(from_attributes=True)

class PayoutAddressIn(BaseModel):
    address:str=Field(min_length=8,max_length=255); chain:str=Field(min_length=2,max_length=32)
    label:str=Field(default="Reward address",min_length=2,max_length=80); make_primary:bool=True

class PayoutAddressOut(BaseModel):
    id:int; address:str; chain:str; label:str; is_primary:bool; verification_status:str; created_at:datetime
    model_config=ConfigDict(from_attributes=True)

class ProjectCreate(BaseModel):
    name:str=Field(min_length=2,max_length=120); symbol:str=Field(min_length=1,max_length=24); description:str=Field(min_length=20,max_length=5000)
    website:str|None=None; chain:str="Avalanche"; logo_url:str|None=None; treasury_address:str|None=None

class ProjectOut(BaseModel):
    id:int; owner_id:int; name:str; slug:str; symbol:str; description:str; website:str|None; chain:str; logo_url:str|None; status:str; created_at:datetime
    model_config=ConfigDict(from_attributes=True)

class MissionCreate(BaseModel):
    title:str; description:str=""; mission_type:str="LEARN"; verification_type:str="SELF_ATTEST"; target_url:str|None=None
    quiz_question:str|None=None; quiz_options:list[str]|None=None; quiz_answer:str|None=None; xp_reward:int=50

class MissionOut(BaseModel):
    id:int; title:str; description:str; mission_type:str; verification_type:str; target_url:str|None; quiz_question:str|None; quiz_options:list[str]|None; xp_reward:int; position:int
    model_config=ConfigDict(from_attributes=True)

class CampaignCreate(BaseModel):
    project_id:int; title:str=Field(min_length=3,max_length=160); description:str=Field(min_length=20,max_length=5000); category:str="DISCOVER"; difficulty:str="EASY"
    reward_asset:str=Field(min_length=1,max_length=24); funding_type:str="TOKEN"; token_allocation:Decimal=Field(gt=0); gross_reward_per_user:Decimal=Field(gt=0)
    user_share_pct:Decimal=Decimal("80"); nubagz_share_pct:Decimal=Decimal("15"); referral_share_pct:Decimal=Decimal("5"); max_users:int=Field(gt=0,le=1_000_000)
    estimated_value_gbp:Decimal|None=None; missions:list[MissionCreate]=Field(min_length=1)
    @model_validator(mode="after")
    def shares_total(self):
        if self.user_share_pct+self.nubagz_share_pct+self.referral_share_pct!=Decimal("100"): raise ValueError("Reward shares must total 100%")
        if self.gross_reward_per_user*self.max_users>self.token_allocation: raise ValueError("Token allocation must cover maximum gross rewards")
        return self

class CampaignOut(BaseModel):
    id:int; project_id:int; title:str; description:str; category:str; difficulty:str; reward_asset:str; funding_type:str; token_allocation:Decimal; gross_reward_per_user:Decimal
    user_share_pct:Decimal; nubagz_share_pct:Decimal; referral_share_pct:Decimal; max_users:int; status:str; featured:bool; estimated_value_gbp:Decimal|None; created_at:datetime
    missions:list[MissionOut]=[]; project:ProjectOut|None=None; enrolled_count:int=0; completed_count:int=0; min_bag_score:int=0; required_tier:str="STARTER"
    model_config=ConfigDict(from_attributes=True)

class MissionCompleteIn(BaseModel): answer:str|None=None
class RewardBalance(BaseModel): asset_symbol:str; amount:Decimal
class WithdrawalIn(BaseModel): asset_symbol:str; amount:Decimal=Field(gt=0); chain:str; wallet_address:str=Field(min_length=8,max_length=255)
class DashboardOut(BaseModel):
    lifetime_assets:int; active_bagz:int; completed_bagz:int; xp:int; bag_score:int; streak_days:int; balances:list[RewardBalance]; recent_activity:list[dict[str,Any]]
class AdminDecision(BaseModel): status:str