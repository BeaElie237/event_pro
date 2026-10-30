"""Scraper contract and shared HTTP plumbing."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import TYPE_CHECKING

import httpx
from pydantic import ValidationError

from eventpro_common.schemas import RawEvent

if TYPE_CHECKING:
    from scrapers.registry import SourceConfig

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """A scraper turns one configured source into a stream of validated RawEvent."""

    def __init__(self, config: SourceConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return self.config.name

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.config.timeout_seconds,
            headers={"User-Agent": self.config.user_agent, **self.config.headers},
            follow_redirects=True,
            transport=httpx.HTTPTransport(retries=3),
        )

    @abstractmethod
    def _iter_records(self, client: httpx.Client) -> Iterator[dict]:
        """Yield raw dicts matching RawEvent fields (``source`` is filled in by ``scrape``)."""

    def scrape(self) -> Iterator[RawEvent]:
        emitted = rejected = 0
        with self._client() as client:
            for record in self._iter_records(client):
                if emitted >= self.config.max_items:
                    break
                try:
                    yield RawEvent.model_validate(
                        {"language": self.config.language, **record, "source": self.name}
                    )
                    emitted += 1
                except ValidationError as exc:
                    rejected += 1
                    logger.warning("[%s] invalid record skipped: %s", self.name, exc.errors()[:2])
        logger.info("[%s] scraped=%d rejected=%d", self.name, emitted, rejected)
