"""Typed application settings.

Everything is read from environment variables prefixed with ``HELIX_`` (or a
local ``.env`` file). No service URL or secret is hardcoded, so the same code
runs locally and in containers.
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "dev", "test", "staging", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HELIX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "helix-api"
    app_env: AppEnv = "local"
    app_version: str = "0.1.0"
    log_level: LogLevel = "INFO"

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_user: str = "helix"
    postgres_password: SecretStr = SecretStr("helix_dev_password")
    postgres_db: str = "helix"

    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0

    qdrant_host: str = "127.0.0.1"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334

    minio_host: str = "127.0.0.1"
    minio_port: int = 9100
    minio_console_port: int = 9101
    minio_user: str = "helix"
    minio_password: SecretStr = SecretStr("helix_minio_dev_password")
    minio_secure: bool = False

    @property
    def postgres_dsn(self) -> str:
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password.get_secret_value())
        return (
            f"postgresql://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    @property
    def minio_endpoint(self) -> str:
        scheme = "https" if self.minio_secure else "http"
        return f"{scheme}://{self.minio_host}:{self.minio_port}"


@lru_cache
def get_settings() -> Settings:
    """Build settings once per process."""
    return Settings()
