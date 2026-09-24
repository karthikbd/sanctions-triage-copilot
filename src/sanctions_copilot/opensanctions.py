"""OpenSanctions integration: download, cache and parse `targets.simple.csv` for one or more datasets.

Data: https://www.opensanctions.org/datasets/  (licence CC BY-NC 4.0: free for non-commercial use;
commercial use requires a data licence from OpenSanctions). Datasets are refreshed several times a day;
each dataset publishes `https://data.opensanctions.org/datasets/latest/<name>/index.json`, which points
to the current versioned artifact.

simple CSV columns: id, schema, name, aliases, birth_date, countries, addresses, identifiers, sanctions,
phones, emails, program_ids, dataset, first_seen, last_seen, last_change  (multi-values separated by ';')
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .models import PartyType, WatchlistEntry

log = logging.getLogger(__name__)

INDEX_URL = "https://data.opensanctions.org/datasets/latest/{name}/index.json"
DEFAULT_DATASETS = ("us_ofac_sdn", "un_sc_sanctions", "eu_fsf", "gb_fcdo_sanctions")
USER_AGENT = "sanctions-triage-copilot/0.2 (+https://github.com/; non-commercial portfolio project)"
ATTRIBUTION = "Sanctions data: OpenSanctions (opensanctions.org), CC BY-NC 4.0"

SCHEMA_MAP = {
    "Person": PartyType.individual,
    "Organization": PartyType.entity,
    "Company": PartyType.entity,
    "LegalEntity": PartyType.entity,
    "PublicBody": PartyType.entity,
    "Vessel": PartyType.vessel,
    "Airplane": PartyType.aircraft,
}

csv.field_size_limit(10_000_000)


@dataclass
class DatasetStatus:
    name: str
    version: str = ""
    entities: int = 0
    fetched_at: Optional[str] = None
    source: str = "none"          # network | cache | none
    error: Optional[str] = None
    path: Optional[str] = None


@dataclass
class LoadResult:
    entries: list[WatchlistEntry]
    datasets: list[DatasetStatus] = field(default_factory=list)

    @property
    def version(self) -> str:
        return "+".join(f"{d.name}@{d.version}" for d in self.datasets if d.version)


def _split(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(";") if x.strip()]


def parse_simple_csv(text_or_rows: str | Iterable[dict], dataset_hint: str = "") -> list[WatchlistEntry]:
    rows = csv.DictReader(io.StringIO(text_or_rows)) if isinstance(text_or_rows, str) else text_or_rows
    out: list[WatchlistEntry] = []
    for r in rows:
        ptype = SCHEMA_MAP.get((r.get("schema") or "").strip())
        name = (r.get("name") or "").strip()
        if ptype is None or not name:
            continue  # skip crypto wallets, securities, addresses, etc.
        programs = _split(r.get("program_ids")) or _split(r.get("dataset")) or ([dataset_hint] if dataset_hint else [])
        sanctions = _split(r.get("sanctions"))
        remarks = "; ".join(sanctions)[:600]
        out.append(WatchlistEntry(
            uid=(r.get("id") or "").strip(),
            name=name,
            aliases=[a for a in _split(r.get("aliases")) if a != name][:60],
            party_type=ptype,
            programs=programs[:12],
            dobs=_split(r.get("birth_date"))[:6],
            countries=_split(r.get("countries")),
            id_numbers=_split(r.get("identifiers"))[:20],
            remarks=remarks or None,
            source="OpenSanctions:" + ",".join(_split(r.get("dataset")) or [dataset_hint]),
        ))
    return out


def _client(timeout: float):
    import httpx

    return httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT})


def fetch_dataset(name: str, cache_dir: Path, client=None, force: bool = False, timeout: float = 120.0) -> DatasetStatus:
    """Download the latest targets.simple.csv for `name` into cache_dir/<name>/ unless that version is cached."""
    st = DatasetStatus(name=name)
    ddir = cache_dir / name
    ddir.mkdir(parents=True, exist_ok=True)
    own = client is None
    client = client or _client(timeout)
    try:
        r = client.get(INDEX_URL.format(name=name))
        r.raise_for_status()
        idx = r.json()
        version = str(idx.get("version") or idx.get("updated_at") or idx.get("last_export") or "unknown")
        url = None
        for res in idx.get("resources", []):
            if res.get("name") == "targets.simple.csv" or str(res.get("url", "")).endswith("/targets.simple.csv"):
                url = res.get("url")
                break
        if not url:
            raise ValueError("index.json has no targets.simple.csv resource")
        target = ddir / f"{_safe(version)}.targets.simple.csv"
        if force or not target.exists():
            tmp = target.with_suffix(".part")
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
            tmp.replace(target)
            (ddir / "current.json").write_text(json.dumps({"version": version, "file": target.name,
                                                           "fetched_at": _now(), "url": url}), encoding="utf-8")
        st.version, st.path, st.source = version, str(target), "network"
        st.fetched_at = json.loads((ddir / "current.json").read_text()).get("fetched_at") if (ddir / "current.json").exists() else _now()
    except Exception as e:  # network down, blocked, schema change: fall back to cache
        st.error = f"{type(e).__name__}: {e}"[:300]
        cur = ddir / "current.json"
        if cur.exists():
            meta = json.loads(cur.read_text(encoding="utf-8"))
            st.version, st.path, st.source, st.fetched_at = meta["version"], str(ddir / meta["file"]), "cache", meta.get("fetched_at")
        log.warning("OpenSanctions %s: %s (using %s)", name, st.error, st.source)
    finally:
        if own:
            client.close()
    return st


def load(datasets: Iterable[str] = DEFAULT_DATASETS, cache_dir: str | Path = "data/opensanctions",
         client=None, force: bool = False) -> LoadResult:
    cache_dir = Path(cache_dir)
    entries: list[WatchlistEntry] = []
    statuses: list[DatasetStatus] = []
    for name in datasets:
        st = fetch_dataset(name, cache_dir, client=client, force=force)
        if st.path and Path(st.path).exists():
            parsed = parse_simple_csv(Path(st.path).read_text(encoding="utf-8", errors="replace"), dataset_hint=name)
            st.entities = len(parsed)
            entries.extend(parsed)
        statuses.append(st)
    return LoadResult(entries=entries, datasets=statuses)


def _safe(v: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in v)[:80]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
