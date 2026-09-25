"""Normalization of names, dates of birth, countries and identifiers.

Screening quality is decided here more than anywhere else: most missed hits in real
programs come from transliteration, name order, punctuation and legal-form noise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Optional

import jellyfish
from unidecode import unidecode

HONORIFICS = {
    "mr", "mrs", "ms", "miss", "dr", "prof", "sir", "dame", "lord", "lady", "haji", "hajji",
    "sheikh", "shaikh", "sheik", "gen", "general", "col", "colonel", "capt", "captain", "maj",
}

# Particles are kept in the text but ignored when checking token coverage/phonetics.
PARTICLES = {"al", "el", "ul", "bin", "ibn", "bint", "abu", "van", "von", "de", "der", "den", "da", "di", "du", "la", "le"}

LEGAL_FORMS = {
    "llc", "ltd", "limited", "inc", "incorporated", "corp", "corporation", "co", "company", "plc", "llp", "lp",
    "gmbh", "ag", "sa", "sas", "sarl", "srl", "spa", "bv", "nv", "oy", "ab", "as", "jsc", "ojsc", "pjsc", "cjsc",
    "ooo", "zao", "oao", "pao", "fze", "fzco", "fzc", "fzllc", "dmcc", "pte", "pty", "sdn", "bhd", "kk", "group",
    "holding", "holdings", "the",
}

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}



@dataclass(frozen=True)
class NormName:
    raw: str
    text: str                 # normalized, space separated, original order
    tokens: tuple[str, ...]
    sorted_text: str          # tokens sorted alphabetically (order-insensitive key)
    core_tokens: tuple[str, ...]  # tokens minus particles
    phonetic: tuple[str, ...]     # metaphone code per core token


def _ascii(s: str) -> str:
    return unidecode(s or "").lower()


@lru_cache(maxsize=200_000)
def normalize_name(raw: str, is_entity: bool = False) -> NormName:
    s = _ascii(raw)
    s = s.replace("&", " and ")
    s = re.sub(r"\b([a-z])\.(?=[a-z]\b)", r"\1", s)  # L.L.C. -> llc., S.A. -> sa.
    s = re.sub(r"[\-_/.,'`\"()\[\]]", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    tokens = [t for t in s.split() if t]
    tokens = [t for t in tokens if t not in HONORIFICS]
    if is_entity:
        stripped = [t for t in tokens if t not in LEGAL_FORMS]
        tokens = stripped or tokens
    core = tuple(t for t in tokens if t not in PARTICLES) or tuple(tokens)
    phon = tuple(phonetic_code(t) for t in core)
    return NormName(
        raw=raw,
        text=" ".join(tokens),
        tokens=tuple(tokens),
        sorted_text=" ".join(sorted(tokens)),
        core_tokens=core,
        phonetic=phon,
    )


@lru_cache(maxsize=200_000)
def phonetic_code(token: str) -> str:
    if token.isdigit():
        return token
    # Collapse common transliteration variation before encoding (Mohammed/Muhammad, Yusuf/Youssef).
    t = re.sub(r"(.)\1+", r"\1", token)          # double letters
    t = t.replace("ou", "u").replace("oo", "u").replace("ee", "i").replace("kh", "h").replace("dh", "d")
    t = re.sub(r"^mu|^mo", "m", t)
    return jellyfish.metaphone(t) or t


# ---------------------------------------------------------------------------------------------
# Dates of birth
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ParsedDOB:
    year_min: int
    year_max: int
    exact: Optional[date] = None
    raw: str = ""


def parse_dob(raw: Optional[str]) -> Optional[ParsedDOB]:
    """Parse the DOB formats that appear in customer data and on sanctions lists.

    Handles: 1971, 1971-03-12, 12/03/1971 (day first), 12 Mar 1971, Mar 1971,
    'circa 1971', '1969 to 1972'.
    """
    if not raw:
        return None
    s = raw.strip().lower().replace(",", " ")
    rng = re.search(r"(\d{4})\s*(?:to|-|–)\s*(\d{4})", s)
    if rng:
        a, b = int(rng.group(1)), int(rng.group(2))
        return ParsedDOB(min(a, b), max(a, b), None, raw)
    iso = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if iso:
        return _mk(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)), raw)
    dmy = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", s)
    if dmy:
        return _mk(int(dmy.group(3)), int(dmy.group(2)), int(dmy.group(1)), raw)
    dmony = re.search(r"(\d{1,2})\s+([a-z]{3})[a-z]*\s+(\d{4})", s)
    if dmony and dmony.group(2) in MONTHS:
        return _mk(int(dmony.group(3)), MONTHS[dmony.group(2)], int(dmony.group(1)), raw)
    year = re.search(r"(\d{4})", s)
    if year:
        y = int(year.group(1))
        slack = 1 if "circa" in s or "approx" in s or "c." in s else 0
        return ParsedDOB(y - slack, y + slack, None, raw)
    return None


def _mk(y: int, m: int, d: int, raw: str) -> ParsedDOB:
    try:
        return ParsedDOB(y, y, date(y, m, d), raw)
    except ValueError:
        return ParsedDOB(y, y, None, raw)


# ---------------------------------------------------------------------------------------------
# Countries and identifiers
# ---------------------------------------------------------------------------------------------

_EXTRA_COUNTRY_ALIASES = {
    "russia": "ru", "russian federation": "ru", "uae": "ae", "emirates": "ae", "iran": "ir",
    "islamic republic of iran": "ir", "iran islamic republic of": "ir", "north korea": "kp", "dprk": "kp",
    "democratic peoples republic of korea": "kp", "korea north": "kp", "korea democratic peoples republic of": "kp",
    "south korea": "kr", "korea south": "kr", "republic of korea": "kr", "korea republic of": "kr",
    "syria": "sy", "syrian arab republic": "sy", "venezuela": "ve", "venezuela bolivarian republic of": "ve",
    "usa": "us", "united states of america": "us", "america": "us", "uk": "gb", "britain": "gb",
    "great britain": "gb", "england": "gb", "turkey": "tr", "turkiye": "tr", "burma": "mm", "vietnam": "vn",
    "viet nam": "vn", "laos": "la", "bolivia": "bo", "taiwan": "tw", "moldova": "md", "tanzania": "tz",
    "czech republic": "cz", "czechia": "cz", "hong kong": "hk", "hong kong sar": "hk", "macau": "mo",
    "palestine": "ps", "ivory coast": "ci", "cote d ivoire": "ci", "drc": "cd", "dr congo": "cd",
    "democratic republic of congo": "cd", "democratic republic of the congo": "cd", "congo democratic republic": "cd",
    "republic of congo": "cg", "british virgin islands": "vg", "virgin islands uk": "vg", "prc": "cn",
    "peoples republic of china": "cn", "china": "cn", "kosovo": "xk", "crimea": "ua", "macedonia": "mk",
    "north macedonia": "mk", "eswatini": "sz", "swaziland": "sz", "cape verde": "cv", "brunei": "bn",
    "bosnia": "ba", "bosnia and herzegovina": "ba", "micronesia": "fm", "st kitts and nevis": "kn",
    "saint kitts and nevis": "kn", "st lucia": "lc", "saint lucia": "lc", "vatican": "va", "holy see": "va",
}


def _clean_country(raw: str) -> str:
    s = re.sub(r"[^a-z ]", " ", _ascii(raw))
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=1)
def _country_tables() -> tuple[dict[str, str], dict[str, str]]:
    import json
    from importlib import resources

    iso = json.loads(resources.files("sanctions_copilot.data").joinpath("iso_countries.json").read_text(encoding="utf-8"))
    by_name: dict[str, str] = {}
    for code, name in iso.items():  # first code wins, so DR Congo's name maps to 'cd', not the retired 'zr'
        by_name.setdefault(_clean_country(name), code)
    by_name.update(_EXTRA_COUNTRY_ALIASES)
    return iso, by_name


def normalize_country(raw: Optional[str]) -> Optional[str]:
    """Return a lowercase ISO-3166 alpha-2 code where possible (both 'Iran' and 'ir' -> 'ir')."""
    if not raw:
        return None
    iso, by_name = _country_tables()
    s = _clean_country(raw)
    if not s:
        return None
    if len(s) == 2 and s in iso:
        return s
    if s in by_name:
        return by_name[s]
    alpha3 = {"usa": "us", "gbr": "gb", "rus": "ru", "irn": "ir", "prk": "kp", "syr": "sy", "chn": "cn", "are": "ae"}
    return alpha3.get(s, s)


@lru_cache(maxsize=1)
def country_options() -> list[dict]:
    """[{code, name, aliases, historic}] sorted by name, for the UI's searchable country picker."""
    iso, _ = _country_tables()
    aliases: dict[str, list[str]] = {}
    for alias, code in _EXTRA_COUNTRY_ALIASES.items():
        aliases.setdefault(code, []).append(alias)
    seen: set[str] = set()
    out = []
    for code, name in iso.items():
        canonical = normalize_country(name)  # e.g. 'zr' (old Zaire code) and 'cd' share a name; keep the one it maps to
        if name in seen or canonical != code:
            continue
        seen.add(name)
        out.append({"code": code, "name": name, "aliases": sorted(aliases.get(code, [])), "historic": len(code) != 2})
    return sorted(out, key=lambda c: (c["historic"], _ascii(c["name"])))


def country_name(code: Optional[str]) -> str:
    if not code:
        return ""
    iso, _ = _country_tables()
    return iso.get(code, code)


def normalize_id(raw: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]", "", unidecode(raw or "")).upper()
    return re.sub(r"^IMO", "", s)
