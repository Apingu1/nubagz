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
    model_config=SettingsConfigDict(env_file=".env",extra="ignore")
    @property
    def cors_origin_list(self)->list[str]: return [item.strip() for item in self.cors_origins.split(",") if item.strip()]
    @property
    def signing_key(self)->str: return (self.jwt_private_key or self.jwt_secret).replace("\\n","\n")
    @property
    def verification_key(self)->str: return (self.jwt_public_key or self.jwt_secret).replace("\\n","\n")

settings=Settings()
