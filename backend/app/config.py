from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NuBagz API"
    environment: str = "development"
    database_url: str = "sqlite:///./nubagz.db"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_private_key: str | None = None
    jwt_public_key: str | None = None
    jwt_key_id: str = "nubagz-1"
    jwt_audience: str = "nubagz-api"
    access_token_minutes: int = 1440
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    privy_app_id: str | None = None
    privy_verification_key: str | None = None
    social_proof_secret: str | None = None

    # Phase 2.5 privileged Admin security. Keep this key stable and separate
    # from JWT signing keys so MFA credentials survive normal signing-key rotation.
    admin_security_key: str | None = None
    admin_privileged_minutes: int = 10
    admin_reauth_max_age_seconds: int = 300

    # EVM RPCs. Robinhood Chain is the primary NuBagz network. Its official
    # public RPC is useful for development but a dedicated provider is still
    # recommended for production throughput.
    evm_rpc_robinhood: str | None = "https://rpc.mainnet.chain.robinhood.com"
    evm_rpc_avalanche: str | None = None
    evm_rpc_ethereum: str | None = None
    evm_rpc_base: str | None = None
    evm_rpc_arbitrum: str | None = None
    evm_rpc_polygon: str | None = None

    # Genuine non-custodial swap routing. NuBagz never holds keys or broadcasts
    # on the user's behalf: providers return executable calldata and the user's
    # connected wallet signs the approval/swap transactions.
    zerox_api_key: str | None = None
    lifi_api_key: str | None = None
    lifi_integrator: str = "nubagz"
    nubagz_swap_fee_bps: int = 75
    nubagz_swap_fee_recipient: str | None = None

    # Retained only for backwards-compatible deployments; the Swap UI no
    # longer uses the old generic provider/intent contract.
    swap_provider_base_url: str | None = None
    swap_provider_api_key: str | None = None
    gas_sponsor_provider_base_url: str | None = None
    gas_sponsor_provider_api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def signing_key(self) -> str:
        return (self.jwt_private_key or self.jwt_secret).replace("\\n", "\n")

    @property
    def verification_key(self) -> str:
        return (self.jwt_public_key or self.jwt_secret).replace("\\n", "\n")

    @property
    def swap_fee_bps(self) -> int:
        return max(0, min(int(self.nubagz_swap_fee_bps), 1000))

    @property
    def privileged_minutes(self) -> int:
        return max(2, min(int(self.admin_privileged_minutes), 30))

    def validate_runtime_security(self) -> None:
        if self.environment.lower() != "production":
            return
        if self.jwt_algorithm.upper() != "RS256":
            raise RuntimeError("Production NuBagz must use JWT_ALGORITHM=RS256")
        if not (self.jwt_private_key or "").strip() or not (self.jwt_public_key or "").strip():
            raise RuntimeError("Production NuBagz requires JWT_PRIVATE_KEY and JWT_PUBLIC_KEY")
        if not (self.jwt_audience or "").strip():
            raise RuntimeError("Production NuBagz requires JWT_AUDIENCE")
        if not (self.admin_security_key or "").strip():
            raise RuntimeError("Production NuBagz requires ADMIN_SECURITY_KEY")


settings = Settings()