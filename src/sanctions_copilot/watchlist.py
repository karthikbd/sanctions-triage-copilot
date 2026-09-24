"""Watchlist loading: bundled fictional sample, JSON files, the OFAC SDN CSV export and OpenSanctions."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from importlib import resources
from pathlib import Path

from .models import PartyType, WatchlistEntry

OFAC_BASE = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports"
OFAC_FILES = {"sdn": "SDN.CSV", "alt": "ALT.CSV", "add": "ADD.CSV"}
NULL = "-0-"


def entry_fingerprint(e: WatchlistEntry) -> str:
    """Content hash of a list entry. A changed entry (new alias, new DOB) gets a new fingerprint, so
    previously cleared alerts are re-raised for review instead of staying suppressed."""
    body = json.dumps(e.model_dump(mode="json", exclude={"source"}), sort_keys=True)
    return hashlib.sha1(body.encode()).hexdigest()[:16]


class Watchlist:
    def __init__(self, entries: list[WatchlistEntry], source: str, version: str = "static",
                 datasets: list[dict] | None = None, attribution: str = ""):
        self.entries = entries
        self.source = source
        self.version = version
        self.datasets = datasets or [{"name": source, "entities": len(entries), "version": version, "source": "bundled"}]
        self.attribution = attribution
        self._by_uid = {e.uid: e for e in entries}

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, uid: str) -> WatchlistEntry | None:
        return self._by_uid.get(uid)


def load_sample() -> Watchlist:
    raw = resources.files("sanctions_copilot.data").joinpath("sample_watchlist.json").read_text(encoding="utf-8")
    return _from_json(json.loads(raw))


def load_json(path: str | Path) -> Watchlist:
    return _from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def _from_json(data: dict) -> Watchlist:
    entries = [WatchlistEntry(**e, source=data.get("source", "JSON")) for e in data["entries"]]
    return Watchlist(entries, data.get("source", "JSON"))


def load_opensanctions(datasets: list[str] | None = None, cache_dir: str = "data/opensanctions",
                       client=None, force: bool = False) -> Watchlist:
    from . import opensanctions as osx

    res = osx.load(datasets or list(osx.DEFAULT_DATASETS), cache_dir=cache_dir, client=client, force=force)
    if not res.entries:
        errs = "; ".join(f"{d.name}: {d.error}" for d in res.datasets if d.error)
        raise RuntimeError(f"OpenSanctions data unavailable and no cache found ({errs})")
    names = ", ".join(d.name for d in res.datasets)
    return Watchlist(res.entries, f"OpenSanctions ({names})", version=res.version,
                     datasets=[d.__dict__ for d in res.datasets], attribution=osx.ATTRIBUTION)


def load(spec: str) -> Watchlist:
    """spec: 'sample' | 'opensanctions' | 'opensanctions:ds1,ds2' | path to .json | folder with OFAC SDN CSVs."""
    if spec in ("", "sample"):
        return load_sample()
    if spec.startswith("opensanctions"):
        ds = spec.split(":", 1)[1].split(",") if ":" in spec else None
        return load_opensanctions([d.strip() for d in ds if d.strip()] if ds else None)
    p = Path(spec)
    if p.is_dir():
        return load_ofac_dir(p)
    return load_json(p)


# ---------------------------------------------------------------------------------------------
# OFAC SDN legacy CSV format
#   SDN.CSV: ent_num, SDN_Name, SDN_Type, Program, Title, Call_Sign, Vess_type, Tonnage, GRT,
#            Vess_flag, Vess_owner, Remarks
#   ALT.CSV: ent_num, alt_num, alt_type, alt_name, alt_remarks
#   ADD.CSV: ent_num, add_num, address, city_state_zip, country, add_remarks
# ---------------------------------------------------------------------------------------------

_DOB_RE = re.compile(r"\bDOB\s+([^;]+)", re.I)
_NAT_RE = re.compile(r"\b(?:nationality|citizen)\s+([^;]+)", re.I)
_ID_RE = re.compile(
    r"\b(?:Passport|National ID No\.|Cedula No\.|Tax ID No\.|Registration Number|Registration ID|"
    r"Identification Number|Vessel Registration Identification|C\.U\.R\.P\.|RFC|NIT #|"
    r"Business Registration Number|Company Number|D-U-N-S Number)\s+([A-Za-z0-9][A-Za-z0-9\-/ ]*?)\s*(?:\(|;|\.$|$)",
    re.I,
)
_TYPE_MAP = {"individual": PartyType.individual, "vessel": PartyType.vessel, "aircraft": PartyType.aircraft}


def _clean(v: str | None) -> str:
    v = (v or "").strip()
    return "" if v == NULL else v


def _read(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        return [row for row in csv.reader(f) if row and _clean(row[0]).isdigit()]


def parse_remarks(remarks: str) -> tuple[list[str], list[str], list[str]]:
    dobs = [m.strip().rstrip(".") for m in _DOB_RE.findall(remarks or "")]
    nats = [m.strip().rstrip(".") for m in _NAT_RE.findall(remarks or "")]
    ids = [m.strip() for m in _ID_RE.findall(remarks or "")]
    return dobs, nats, ids


def _find(folder: Path, name: str) -> Path:
    for cand in (name, name.lower()):
        p = folder / cand
        if p.exists():
            return p
    return folder / name


def load_ofac_dir(folder: str | Path) -> Watchlist:
    folder = Path(folder)
    sdn = _read(_find(folder, OFAC_FILES["sdn"]))
    if not sdn:
        raise FileNotFoundError(f"No SDN.CSV found in {folder}. Run `stc load-ofac --dest {folder}` first.")
    alts: dict[str, list[str]] = defaultdict(list)
    for row in _read(_find(folder, OFAC_FILES["alt"])):
        if len(row) >= 4 and _clean(row[3]):
            alts[row[0].strip()].append(_clean(row[3]))
    countries: dict[str, set[str]] = defaultdict(set)
    for row in _read(_find(folder, OFAC_FILES["add"])):
        if len(row) >= 5 and _clean(row[4]):
            countries[row[0].strip()].add(_clean(row[4]))

    entries = []
    for row in sdn:
        row = row + [""] * (12 - len(row))
        uid = row[0].strip()
        remarks = _clean(row[11])
        dobs, nats, ids = parse_remarks(remarks)
        ctry = set(countries.get(uid, set())) | set(nats)
        if _clean(row[9]):
            ctry.add(_clean(row[9]))  # vessel flag
        programs = [p.strip(" []") for p in re.split(r"\]\s*\[", _clean(row[3])) if p.strip(" []")]
        entries.append(
            WatchlistEntry(
                uid=f"OFAC-{uid}",
                name=_clean(row[1]),
                aliases=alts.get(uid, []),
                party_type=_TYPE_MAP.get(_clean(row[2]).lower(), PartyType.entity),
                programs=programs,
                dobs=dobs,
                countries=sorted(ctry),
                id_numbers=ids,
                remarks=remarks[:1000],
                source="OFAC SDN",
            )
        )
    return Watchlist(entries, "OFAC SDN")


def download_ofac(dest: str | Path, timeout: float = 60.0) -> Path:
    """Download the current OFAC SDN legacy CSV files (public, no auth)."""
    import httpx

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for fname in OFAC_FILES.values():
            r = client.get(f"{OFAC_BASE}/{fname}")
            r.raise_for_status()
            (dest / fname).write_bytes(r.content)
    return dest
