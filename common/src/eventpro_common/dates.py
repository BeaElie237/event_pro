"""Robust date parsing for heterogeneous sources (ISO, English and French formats)."""

from __future__ import annotations

import re
from datetime import date, datetime

from dateutil import parser as date_parser

from eventpro_common.text import strip_accents

_FR_MONTHS = {
    "janvier": "january", "fevrier": "february", "mars": "march", "avril": "april",
    "mai": "may", "juin": "june", "juillet": "july", "aout": "august",
    "septembre": "september", "octobre": "october", "novembre": "november", "decembre": "december",
    "janv": "jan", "fevr": "feb", "avr": "apr", "juil": "jul", "sept": "sep", "oct": "oct", "nov": "nov", "dec": "dec",
}
_FR_MONTH_PATTERN = re.compile(r"\b(" + "|".join(sorted(_FR_MONTHS, key=len, reverse=True)) + r")\.?\b")
_FR_NOISE = re.compile(r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|le|du|au)\b")
_FIRST_OF_MONTH = re.compile(r"\b1er\b")
_ORDINAL_SUFFIX = re.compile(r"\b(\d{1,2})(st|nd|rd|th)\b")

_ISO_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")

_MIN_YEAR, _MAX_YEAR = 2000, 2100
_NO_YEAR_SENTINEL = 1


def parse_date(value: str | date | datetime | None, *, dayfirst: bool = True) -> date | None:
    """Parse a date, returning ``None`` when absent, ambiguous (no year) or implausible."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = strip_accents(str(value)).lower().strip()
    if not text:
        return None
    # ISO first: dateutil with dayfirst=True would read "2026-12-01" as 12 January.
    iso = _ISO_PREFIX.match(text)
    if iso:
        try:
            return date.fromisoformat(iso.group(0))
        except ValueError:
            return None
    text = _FIRST_OF_MONTH.sub("1", text)
    text = _ORDINAL_SUFFIX.sub(r"\1", text)
    text = _FR_MONTH_PATTERN.sub(lambda m: _FR_MONTHS[m.group(1)], text)
    text = _FR_NOISE.sub(" ", text)

    try:
        parsed = date_parser.parse(
            text,
            dayfirst=dayfirst,
            fuzzy=True,
            default=datetime(_NO_YEAR_SENTINEL, 1, 1),
        )
    except (ValueError, OverflowError):
        return None

    if parsed.year == _NO_YEAR_SENTINEL or not _MIN_YEAR <= parsed.year <= _MAX_YEAR:
        return None
    return parsed.date()


_RANGE_SEPARATOR = re.compile(r"\s+(?:au|to|until|jusqu au|-|–|—)\s+", re.IGNORECASE)


def parse_date_range(value: str | None) -> tuple[date | None, date | None]:
    """Parse "12 au 15 mars 2026" / "March 3 - 5, 2026" style ranges into (start, end)."""
    if not value:
        return None, None
    parts = _RANGE_SEPARATOR.split(strip_accents(value).replace("’", " ").strip(), maxsplit=1)
    if len(parts) == 1:
        single = parse_date(parts[0])
        return single, None

    left, right = parts
    end = parse_date(right)
    start = parse_date(left)
    if start is None and end is not None:
        day = re.sub(r"\D", "", re.sub(r"^\D*(\d{1,2}).*$", r"\1", left))
        if day.isdigit() and 1 <= int(day) <= 31:
            try:
                start = end.replace(day=int(day))
            except ValueError:
                start = None
    if start and end and end < start:
        end = None
    return start, end
