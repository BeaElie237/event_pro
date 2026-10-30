"""Application settings, loaded from environment variables (12-factor)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from eventpro_common.embeddings import DEFAULT_MODEL, EMBEDDING_DIM

_INSECURE_SECRETS = {"", "change-me", "change-me-api-jwt"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "EventPro API"
    environment: Literal["local", "test", "staging", "production"] = "local"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=list)
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://eventpro:eventpro@localhost:5432/eventpro"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_echo: bool = False

    jwt_secret_key: SecretStr = SecretStr("change-me")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    embedding_model: str = DEFAULT_MODEL
    embedding_dim: int = EMBEDDING_DIM
    embedding_warmup: bool = True

    # Candidats récupérés par l'index HNSW avant re-ranking métier
    recommendation_candidate_pool: int = Field(default=200, ge=10, le=1000)
    hnsw_ef_search: int = Field(default=100, ge=10, le=1000)

    @model_validator(mode="after")
    def _forbid_default_secret_in_production(self) -> Settings:
        if self.environment in {"staging", "production"} and (
            self.jwt_secret_key.get_secret_value() in _INSECURE_SECRETS
        ):
            raise ValueError("JWT_SECRET_KEY must be set to a strong secret outside local/test")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
