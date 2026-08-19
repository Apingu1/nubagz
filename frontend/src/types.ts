export type User = {
  id:number; email:string; username:string; role:string; xp:number; bag_score:number; streak_days:number;
  referral_code:string; wallet_address?:string|null; wallet_chain?:string|null; created_at:string;
}
export type WalletConnection = {id:number;address:string;chain_type:string;chain_id?:number|null;wallet_client_type:string;connector_type:string;wallet_type:string;is_primary:boolean;verified_at?:string|null;last_connected_at:string;created_at:string}
export type PayoutAddress = {id:number;address:string;chain:string;label:string;is_primary:boolean;verification_status:string;created_at:string}
export type Project = { id:number; owner_id:number; name:string; slug:string; symbol:string; description:string; website?:string|null; chain:string; logo_url?:string|null; status:string; created_at:string }
export type Mission = { id:number; title:string; description:string; mission_type:string; verification_type:string; target_url?:string|null; quiz_question?:string|null; quiz_options?:string[]|null; xp_reward:number; position:number }
export type Campaign = { id:number; project_id:number; title:string; description:string; category:string; difficulty:string; reward_asset:string; funding_type:string; token_allocation:string; gross_reward_per_user:string; user_share_pct:string; nubagz_share_pct:string; referral_share_pct:string; max_users:number; status:string; featured:boolean; estimated_value_gbp?:string|null; created_at:string; missions:Mission[]; project?:Project|null; enrolled_count:number; completed_count:number }
export type Dashboard = { lifetime_assets:number; active_bagz:number; completed_bagz:number; xp:number; bag_score:number; streak_days:number; balances:{asset_symbol:string;amount:string}[]; recent_activity:{asset:string;amount:string;type:string;note?:string;created_at:string}[] }
