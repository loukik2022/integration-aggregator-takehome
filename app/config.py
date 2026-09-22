"""Configuration management for Integration Aggregator."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server Settings
    host: str = Field(default="0.0.0.0", description="Bind host")
    port: int = Field(default=8080, description="Bind port")
    log_level: str = Field(default="INFO", description="Log level")

    # OpenBao Settings
    openbao_addr: str = Field(
        default="http://openbao:8200",
        description="Address of the OpenBao server",
    )
    openbao_token: str = Field(
        default="",
        description="Authentication token for OpenBao",
    )
    openbao_mount_path: str = Field(
        default="oauth2",
        description="Mount path for secrets-oauthapp plugin",
    )
    openbao_timeout: float = Field(
        default=10.0,
        description="Timeout in seconds for OpenBao HTTP requests",
    )

    # Async & State Settings
    worker_concurrency: int = Field(
        default=5,
        description="Number of concurrent worker tasks for async requests",
    )
    state_ttl_seconds: int = Field(
        default=600,
        description="TTL in seconds for OAuth state records (10 mins)",
    )
    request_ttl_seconds: int = Field(
        default=600,
        description="TTL in seconds for async request status records",
    )


settings = Settings()
