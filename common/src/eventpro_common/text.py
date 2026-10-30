"""Text, URL and fingerprint helpers used for cleaning and deduplication."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_HTML_TAG = re.compile(r"<[^>]+>")
_BLOCK_TAG = re.compile(r"</?(p|br|div|li|ul|ol|h[1-6])[^>]*>", re.IGNORECASE)

_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid"})


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_whitespace(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def normalize_text(value: str | None) -> str:
    """Lowercase, accent-free, alphanumeric-only form used for matching and hashing."""
    if not value:
        return ""
    ascii_lower = strip_accents(value).lower()
    return normalize_whitespace(_NON_ALNUM.sub(" ", ascii_lower))


def clean_html(value: str | None) -> str:
    """Convert an HTML fragment (RSS summaries, API descriptions) to plain text."""
    if not value:
        return ""
    text = _BLOCK_TAG.sub("\n", value)
    text = _HTML_TAG.sub(" ", text)
    text = html.unescape(text)
    lines = (normalize_whitespace(line) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def canonicalize_url(url: str | None) -> str | None:
    """Canonical form of an event URL: https, no www, no tracking params, no fragment."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None

    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    query = urlencode(
        sorted(
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=False)
            if key.lower() not in _TRACKING_PARAMS
            and not key.lower().startswith(_TRACKING_PARAM_PREFIXES)
        )
    )
    return urlunsplit(("https", host, path, query, ""))


def compute_fingerprint(title: str, anchor_date: date | None, place: str | None) -> str:
    """Deterministic deduplication key shared by batch and streaming.

    ``anchor_date`` is the start date, or the application deadline for
    opportunities without a start date (scholarships, grants...).
    ``place`` should be the ISO country code when known, else the raw location.
    """
    parts = (
        normalize_text(title),
        anchor_date.isoformat() if anchor_date else "",
        normalize_text(place),
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
