"""RSS/Atom scraper for opportunity blogs (WordPress feeds, etc.)."""

from __future__ import annotations

import re
from collections.abc import Iterator

import feedparser
import httpx

from eventpro_common.text import clean_html
from scrapers.base import BaseScraper

# "Deadline: March 15, 2026" / "Date limite : 15 mars 2026"
_DEADLINE = re.compile(
    r"(?:application\s+)?(?:deadline|date\s+limite|closing\s+date)\s*[:\-–]?\s*([^\n|]{4,40})",
    re.IGNORECASE,
)
_LOCATION = re.compile(r"(?:location|lieu|venue|host\s+country)\s*[:\-–]\s*([^\n|]{2,80})", re.IGNORECASE)


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip(" .") if match else None


class RssScraper(BaseScraper):
    def _iter_records(self, client: httpx.Client) -> Iterator[dict]:
        response = client.get(self.config.url, params=self.config.params)
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        for entry in feed.entries:
            body_html = entry.get("content", [{}])[0].get("value") or entry.get("summary", "")
            body = clean_html(body_html)
            yield {
                "source_event_id": entry.get("id") or entry.get("link"),
                "title": clean_html(entry.get("title", "")),
                "description": body,
                "url": entry.get("link"),
                "deadline": _first(_DEADLINE, body),
                "location": _first(_LOCATION, body),
                "category_hint": " ".join(t.get("term", "") for t in entry.get("tags", [])) or None,
                "tags": [t.get("term", "") for t in entry.get("tags", [])],
                "extra": {"published": entry.get("published"), "author": entry.get("author")},
            }
