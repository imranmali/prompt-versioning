"""Runtime configuration loaded from ``PROMPTLAB_*`` environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROMPTLAB_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite+aiosqlite:///./promptlab.db"
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=20, ge=0)
    db_pool_recycle_seconds: int = Field(default=1800, ge=-1)
    db_echo: bool = False

    auth_enabled: bool = True
    bootstrap_admin_key: SecretStr | None = None

    log_level: str = "INFO"
    log_json: bool = True
    metrics_enabled: bool = True
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    resolve_cache_ttl_seconds: float = Field(default=2.0, ge=0)
    resolve_cache_max_entries: int = Field(default=10_000, ge=1)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
