from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class StreamingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    kafka_bootstrap_servers: str = "localhost:19092"
    kafka_topic_events: str = "events.incoming"
    kafka_topic_dlq: str = "events.dlq"
    kafka_consumer_group: str = "eventpro-ingestion"

    webhook_secret: SecretStr = SecretStr("")
    webhook_require_signature: bool = True
    webhook_max_batch: int = Field(default=500, ge=1)

    database_dsn: str = "postgresql://eventpro:eventpro@localhost:5432/eventpro"
    consumer_batch_size: int = Field(default=100, ge=1, le=1000)
    consumer_poll_timeout_ms: int = 1000

    log_level: str = "INFO"


@lru_cache
def get_settings() -> StreamingSettings:
    return StreamingSettings()
