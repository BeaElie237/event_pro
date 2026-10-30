"""Source configuration (sources.yaml) and scraper factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from scrapers.base import BaseScraper


class SourceConfig(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9_]+$")
    type: Literal["rss", "json_api"]
    url: str
    enabled: bool = True
    language: str | None = None
    timeout_seconds: float = 30
    max_items: int = 200
    user_agent: str = "EventProBot/0.1"
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    # json_api only
    items_path: str | None = None
    field_map: dict[str, str] = Field(default_factory=dict)


def load_sources(path: str | Path, *, only_enabled: bool = True) -> list[SourceConfig]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    defaults: dict[str, Any] = document.get("defaults", {})
    sources = [SourceConfig.model_validate({**defaults, **raw}) for raw in document.get("sources", [])]
    return [s for s in sources if s.enabled or not only_enabled]


def build_scraper(config: SourceConfig) -> BaseScraper:
    from scrapers.json_api import JsonApiScraper
    from scrapers.rss import RssScraper

    scrapers: dict[str, type[BaseScraper]] = {"rss": RssScraper, "json_api": JsonApiScraper}
    return scrapers[config.type](config)
