"""Lightweight country / city detection focused on Africa (plus frequent hosts worldwide).

Deliberately dependency-free: good enough to route and score events. A real
geocoder can replace ``detect_location`` later without touching callers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from eventpro_common.text import normalize_text

AFRICA = "Africa"


@dataclass(frozen=True, slots=True)
class GeoMatch:
    country_code: str
    country_name: str
    continent: str
    city: str | None = None

    @property
    def is_africa(self) -> bool:
        return self.continent == AFRICA


# ISO2 -> (English name, continent, extra aliases incl. French names)
_COUNTRIES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "DZ": ("Algeria", AFRICA, ("algerie",)),
    "AO": ("Angola", AFRICA, ()),
    "BJ": ("Benin", AFRICA, ()),
    "BW": ("Botswana", AFRICA, ()),
    "BF": ("Burkina Faso", AFRICA, ()),
    "BI": ("Burundi", AFRICA, ()),
    "CV": ("Cabo Verde", AFRICA, ("cape verde", "cap vert")),
    "CM": ("Cameroon", AFRICA, ("cameroun",)),
    "CF": ("Central African Republic", AFRICA, ("republique centrafricaine", "centrafrique")),
    "TD": ("Chad", AFRICA, ("tchad",)),
    "KM": ("Comoros", AFRICA, ("comores",)),
    "CG": ("Republic of the Congo", AFRICA, ("congo brazzaville", "congo")),
    "CD": ("Democratic Republic of the Congo", AFRICA, (
        "drc", "dr congo", "rdc", "republique democratique du congo", "congo kinshasa",
    )),
    "CI": ("Cote d'Ivoire", AFRICA, ("ivory coast",)),
    "DJ": ("Djibouti", AFRICA, ()),
    "EG": ("Egypt", AFRICA, ("egypte",)),
    "GQ": ("Equatorial Guinea", AFRICA, ("guinee equatoriale",)),
    "ER": ("Eritrea", AFRICA, ("erythree",)),
    "SZ": ("Eswatini", AFRICA, ("swaziland",)),
    "ET": ("Ethiopia", AFRICA, ("ethiopie",)),
    "GA": ("Gabon", AFRICA, ()),
    "GM": ("Gambia", AFRICA, ("the gambia", "gambie")),
    "GH": ("Ghana", AFRICA, ()),
    "GN": ("Guinea", AFRICA, ("guinee", "guinee conakry")),
    "GW": ("Guinea-Bissau", AFRICA, ("guinee bissau",)),
    "KE": ("Kenya", AFRICA, ()),
    "LS": ("Lesotho", AFRICA, ()),
    "LR": ("Liberia", AFRICA, ()),
    "LY": ("Libya", AFRICA, ("libye",)),
    "MG": ("Madagascar", AFRICA, ()),
    "MW": ("Malawi", AFRICA, ()),
    "ML": ("Mali", AFRICA, ()),
    "MR": ("Mauritania", AFRICA, ("mauritanie",)),
    "MU": ("Mauritius", AFRICA, ("ile maurice",)),
    "MA": ("Morocco", AFRICA, ("maroc",)),
    "MZ": ("Mozambique", AFRICA, ()),
    "NA": ("Namibia", AFRICA, ("namibie",)),
    "NE": ("Niger", AFRICA, ()),
    "NG": ("Nigeria", AFRICA, ()),
    "RW": ("Rwanda", AFRICA, ()),
    "ST": ("Sao Tome and Principe", AFRICA, ("sao tome et principe",)),
    "SN": ("Senegal", AFRICA, ()),
    "SC": ("Seychelles", AFRICA, ()),
    "SL": ("Sierra Leone", AFRICA, ()),
    "SO": ("Somalia", AFRICA, ("somalie",)),
    "ZA": ("South Africa", AFRICA, ("afrique du sud",)),
    "SS": ("South Sudan", AFRICA, ("soudan du sud",)),
    "SD": ("Sudan", AFRICA, ("soudan",)),
    "TZ": ("Tanzania", AFRICA, ("tanzanie",)),
    "TG": ("Togo", AFRICA, ()),
    "TN": ("Tunisia", AFRICA, ("tunisie",)),
    "UG": ("Uganda", AFRICA, ("ouganda",)),
    "ZM": ("Zambia", AFRICA, ("zambie",)),
    "ZW": ("Zimbabwe", AFRICA, ()),
    # Frequent hosts outside Africa
    "FR": ("France", "Europe", ()),
    "BE": ("Belgium", "Europe", ("belgique",)),
    "CH": ("Switzerland", "Europe", ("suisse",)),
    "DE": ("Germany", "Europe", ("allemagne",)),
    "GB": ("United Kingdom", "Europe", ("uk", "england", "royaume uni")),
    "NL": ("Netherlands", "Europe", ("pays bas",)),
    "ES": ("Spain", "Europe", ("espagne",)),
    "IT": ("Italy", "Europe", ("italie",)),
    "PT": ("Portugal", "Europe", ()),
    "SE": ("Sweden", "Europe", ("suede",)),
    "US": ("United States", "North America", ("usa", "united states of america", "etats unis")),
    "CA": ("Canada", "North America", ()),
    "BR": ("Brazil", "South America", ("bresil",)),
    "CN": ("China", "Asia", ("chine",)),
    "JP": ("Japan", "Asia", ("japon",)),
    "KR": ("South Korea", "Asia", ("korea", "coree du sud")),
    "IN": ("India", "Asia", ("inde",)),
    "AE": ("United Arab Emirates", "Asia", ("uae", "dubai", "emirats arabes unis")),
    "QA": ("Qatar", "Asia", ()),
    "TR": ("Turkey", "Asia", ("turkiye", "turquie")),
    "AU": ("Australia", "Oceania", ("australie",)),
}

# Major event hubs -> ISO2
_CITIES: dict[str, str] = {
    "lagos": "NG", "abuja": "NG", "nairobi": "KE", "mombasa": "KE", "accra": "GH", "kumasi": "GH",
    "dakar": "SN", "kigali": "RW", "abidjan": "CI", "douala": "CM", "yaounde": "CM",
    "johannesburg": "ZA", "cape town": "ZA", "durban": "ZA", "pretoria": "ZA", "cairo": "EG", "le caire": "EG",
    "addis ababa": "ET", "casablanca": "MA", "rabat": "MA", "marrakech": "MA", "tunis": "TN",
    "kampala": "UG", "dar es salaam": "TZ", "arusha": "TZ", "kinshasa": "CD", "lome": "TG", "cotonou": "BJ",
    "ouagadougou": "BF", "bamako": "ML", "libreville": "GA", "lusaka": "ZM", "harare": "ZW", "algiers": "DZ",
    "alger": "DZ", "luanda": "AO", "maputo": "MZ", "windhoek": "NA", "gaborone": "BW", "niamey": "NE",
    "paris": "FR", "geneva": "CH", "geneve": "CH", "brussels": "BE", "bruxelles": "BE", "london": "GB",
    "berlin": "DE", "new york": "US", "montreal": "CA", "toronto": "CA",
}


@lru_cache(maxsize=1)
def _index() -> tuple[re.Pattern[str], dict[str, tuple[str, str | None]]]:
    lookup: dict[str, tuple[str, str | None]] = {}
    for code, (name, _, aliases) in _COUNTRIES.items():
        for alias in (name, *aliases):
            lookup[normalize_text(alias)] = (code, None)
    for city, code in _CITIES.items():
        lookup.setdefault(normalize_text(city), (code, city.title()))
    # Longest aliases first so "south sudan" wins over "sudan", "guinea bissau" over "guinea".
    alternatives = sorted(lookup, key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(re.escape(a) for a in alternatives) + r")\b")
    return pattern, lookup


def detect_location(*texts: str | None) -> GeoMatch | None:
    """Return the first country/city found, scanning texts in order of reliability."""
    pattern, lookup = _index()
    for text in texts:
        normalized = normalize_text(text)
        if not normalized:
            continue
        match = pattern.search(normalized)
        if match:
            code, city = lookup[match.group(1)]
            name, continent, _ = _COUNTRIES[code]
            return GeoMatch(country_code=code, country_name=name, continent=continent, city=city)
    return None


def country_info(code: str | None) -> GeoMatch | None:
    if not code:
        return None
    entry = _COUNTRIES.get(code.upper())
    if entry is None:
        return None
    name, continent, _ = entry
    return GeoMatch(country_code=code.upper(), country_name=name, continent=continent)
