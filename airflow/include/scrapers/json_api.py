"""Generic paginated-less JSON API scraper driven by a declarative field map."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from scrapers.base import BaseScraper


def _get_path(obj: Any, dotted: str | None) -> Any:
    """Resolve ``a.b.0.c`` inside nested dicts/lists; ``None`` when missing."""
    if not dotted:
        return obj
    current = obj
    for key in dotted.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
        else:
            return None
    return current


class JsonApiScraper(BaseScraper):
    def _iter_records(self, client: httpx.Client) -> Iterator[dict]:
        response = client.get(self.config.url, params=self.config.params)
        response.raise_for_status()
        items = _get_path(response.json(), self.config.items_path) or []
        if not isinstance(items, list):
            raise ValueError(f"items_path {self.config.items_path!r} does not point to a list")

        for item in items:
            record = {field: _get_path(item, path) for field, path in self.config.field_map.items()}
            record["extra"] = {"api_item": item}
            yield record
