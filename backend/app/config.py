from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name:str="NuBagz API"
    environment:str="development"
    database_url:str="sqlite:///./nubagz.db"
    jwt_secret:str="change-me-in-production"
    jwt_algorithm:str="HS256"
    jwt_private_key:str|None=None
    jwt_public_key:str|None=None
    jwt_key_id:str="nubagz-1"
    access_token_minutes:int=1440
    cors_origins:str="http://localhost:5173,http://127.0.0.1:5173"
    privy_app_id:str|None=None
    privy_verification_key:str|None=None
    x_api_bearer_token:str|None=None
    x_api_base_url:str="https://api.x.com/2"
    evm_rpc_avalanche:str|None=None
    evm_rpc_ethereum:str|None=None
    evm_rpc_base:str|None=None
    evm_rpc_arbitrum:str|None=None
    evm_rpc_polygon:str|None=None
    swap_provider_base_url:str|None=None
    swap_provider_api_key:str|None=None
    gas_sponsor_provider_base_url:str|None=None
    gas_sponsor_provider_api_key:str|None=None
    model_config=SettingsConfigDict(env_file=".env",extra="ignore")
    @property
    def cors_origin_list(self)->list[str]: return [item.strip() for item in self.cors_origins.split(",") if item.strip()]
    @property
    def signing_key(self)->str: return (self.jwt_private_key or self.jwt_secret).replace("\\n","\n")
    @property
    def verification_key(self)->str: return (self.jwt_public_key or self.jwt_secret).replace("\\n","\n")

settings=Settings()
