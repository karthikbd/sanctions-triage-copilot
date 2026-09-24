"""Postgres (Supabase) backend: alert store, audit chain, customers, jobs and a SQL-backed screener.

Used when STC_DATABASE_URL is set (Vercel + Supabase deployment, GitHub Actions worker). The SQLite +
in-memory path in store.py / matcher.py stays the default for local runs and tests.

Screening in Postgres: every list name is stored with its blocking keys (phonetic code and 3-letter prefix
per token) in a GIN-indexed text[] column. A query fetches only names sharing keys with at least two
distinct query tokens, then scores them in Python with the same name_score used locally, so results are
identical to the in-memory screener while the serverless function holds no index in memory.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from contextlib import contextmanager
from typing import Iterable, Optional

import psycopg

from .matcher import Screener, name_score
from .models import Alert, AlertStatus, Candidate, Party, PartyType, WatchlistEntry, utcnow
from .normalize import normalize_name
from .signals import ORG_TYPES, compute_signals
from .watchlist import Watchlist, entry_fingerprint
from .pg_url import DatabaseURLError, clean_db_url, describe_db_url  # noqa: F401

GENESIS = "0" * 64
AUDIT_LOCK = 424242
ENTRY_COLS = "uid, name, party_type, aliases, programs, dobs, countries, id_numbers, remarks, source"


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class PgDB:
    """One lazily-opened autocommit connection per process, re-opened after failures.
    prepare_threshold=None keeps it compatible with Supabase's transaction pooler (port 6543)."""

    def __init__(self, url: str, connect_timeout: int = 15):
        self.url = clean_db_url(url)
        self.connect_timeout = connect_timeout
        self._conn: Optional[psycopg.Connection] = None
        self._lock = threading.RLock()

    def conn(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.url, autocommit=True, prepare_threshold=None,
                                         connect_timeout=self.connect_timeout)
        return self._conn

    def q(self, sql: str, params=None) -> list[tuple]:
        with self._lock:
            for attempt in (1, 2):
                try:
                    with self.conn().cursor() as cur:
                        cur.execute(sql, params)
                        return cur.fetchall() if cur.description else []
                except psycopg.OperationalError:
                    self._conn = None
                    if attempt == 2:
                        raise
        return []

    @contextmanager
    def tx(self):
        with self._lock:
            c = self.conn()
            with c.transaction():
                with c.cursor() as cur:
                    yield cur


# ------------------------------------------------------------------------------------------------
# Store
# ------------------------------------------------------------------------------------------------

class PgStore:
    backend = "postgres"

    def __init__(self, db: PgDB):
        self.db = db

    # alerts
    def save_alert(self, a: Alert) -> None:
        self.db.q(
            "insert into stc.alerts(alert_id, request_id, created_at, status, priority, origin, dedupe_key, body) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict (alert_id) do update set status=excluded.status, "
            "priority=excluded.priority, body=excluded.body",
            (a.alert_id, a.request_id, a.created_at, a.status.value, a.priority.value, a.origin, a.dedupe_key,
             a.model_dump_json()))

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        r = self.db.q("select body::text from stc.alerts where alert_id=%s", (alert_id,))
        return Alert.model_validate_json(r[0][0]) if r else None

    def find_by_dedupe_key(self, key: str) -> Optional[Alert]:
        r = self.db.q("select body::text from stc.alerts where dedupe_key=%s order by created_at desc limit 1", (key,))
        return Alert.model_validate_json(r[0][0]) if r else None

    def clear_alerts(self) -> int:
        r = self.db.q("with d as (delete from stc.alerts returning 1) select count(*) from d")
        return int(r[0][0])

    def list_alerts(self, status: Optional[str] = None, limit: int = 200) -> list[Alert]:
        order = "case priority when 'high' then 0 when 'medium' then 1 else 2 end, created_at desc"
        if status:
            rows = self.db.q(f"select body::text from stc.alerts where status=%s order by {order} limit %s", (status, limit))
        else:
            rows = self.db.q(f"select body::text from stc.alerts order by {order} limit %s", (limit,))
        return [Alert.model_validate_json(r[0]) for r in rows]

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in AlertStatus}
        out.update({k: int(v) for k, v in self.db.q("select status, count(*) from stc.alerts group by status")})
        return out

    def count_by_origin(self) -> dict[str, int]:
        return {k: int(v) for k, v in self.db.q("select origin, count(*) from stc.alerts group by origin")}

    def review_stats(self) -> tuple[int, int]:
        r = self.db.q("select count(*), count(*) filter (where body->'review'->>'outcome' = body->'decision'->>'verdict') "
                      "from stc.alerts where body ? 'review' and body->'review' <> 'null'::jsonb")
        return int(r[0][0]), int(r[0][1])

    # kv
    def kv_get(self, k: str) -> Optional[str]:
        r = self.db.q("select v from stc.kv where k=%s", (k,))
        return r[0][0] if r else None

    def kv_set(self, k: str, v: str) -> None:
        self.db.q("insert into stc.kv(k, v) values (%s,%s) on conflict (k) do update set v=excluded.v", (k, v))

    # audit (hash chain; an advisory lock serialises writers across serverless instances)
    def audit(self, actor: str, event: str, ref: Optional[str], payload: dict) -> str:
        with self.db.tx() as cur:
            cur.execute("select pg_advisory_xact_lock(%s)", (AUDIT_LOCK,))
            cur.execute("select hash from stc.audit order by seq desc limit 1")
            row = cur.fetchone()
            prev = row[0] if row else GENESIS
            ts = utcnow()
            body = {"ts": ts, "actor": actor, "event": event, "ref": ref, "payload": payload}
            h = hashlib.sha256((prev + _canon(body)).encode()).hexdigest()
            cur.execute("insert into stc.audit(ts, actor, event, ref, payload, prev_hash, hash) values (%s,%s,%s,%s,%s,%s,%s)",
                        (ts, actor, event, ref, _canon(payload), prev, h))
            return h

    def audit_trail(self, ref: Optional[str] = None, limit: int = 500) -> list[dict]:
        sql = "select seq, ts, actor, event, ref, payload, prev_hash, hash from stc.audit"
        rows = self.db.q(sql + " where ref=%s order by seq limit %s", (ref, limit)) if ref else \
            self.db.q(sql + " order by seq limit %s", (limit,))
        return [{"seq": r[0], "ts": r[1], "actor": r[2], "event": r[3], "ref": r[4], "payload": json.loads(r[5]),
                 "prev_hash": r[6], "hash": r[7]} for r in rows]

    def verify_audit(self) -> dict:
        prev, n, last = GENESIS, 0, 0
        while True:
            rows = self.db.q("select seq, ts, actor, event, ref, payload, prev_hash, hash from stc.audit "
                             "where seq > %s order by seq limit 5000", (last,))
            if not rows:
                break
            for seq, ts, actor, event, ref, payload, prev_hash, h in rows:
                body = {"ts": ts, "actor": actor, "event": event, "ref": ref, "payload": json.loads(payload)}
                if prev_hash != prev or h != hashlib.sha256((prev + _canon(body)).encode()).hexdigest():
                    return {"valid": False, "records": n, "broken_at_seq": seq}
                prev, n, last = h, n + 1, seq
        return {"valid": True, "records": n, "head": prev}

    # customers
    def replace_customers(self, customers: list[dict], labels: dict[str, dict]) -> None:
        with self.db.tx() as cur:
            cur.execute("delete from stc.customers")
            with cur.copy("copy stc.customers (customer_id, seq, data, label, list_uid, method) from stdin") as cp:
                for i, c in enumerate(customers):
                    lab = labels.get(c["customer_id"], {})
                    cp.write_row((c["customer_id"], i, json.dumps(c), lab.get("label", "none"),
                                  lab.get("list_uid") or None, lab.get("method")))

    def load_customers(self) -> tuple[list[dict], dict[str, dict]]:
        rows = self.db.q("select customer_id, data::text, label, list_uid, method from stc.customers order by seq")
        customers = [json.loads(r[1]) for r in rows]
        labels = {r[0]: {"customer_id": r[0], "label": r[2], "list_uid": r[3] or "", "method": r[4] or ""} for r in rows}
        return customers, labels

    # jobs
    def save_job(self, j) -> None:
        self.db.q("insert into stc.jobs(job_id, kind, status, progress, total, started_at, finished_at, result, error) "
                  "values (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) on conflict (job_id) do update set status=excluded.status, "
                  "progress=excluded.progress, total=excluded.total, finished_at=excluded.finished_at, "
                  "result=excluded.result, error=excluded.error",
                  (j.job_id, j.kind, j.status, j.progress, j.total, j.started_at, j.finished_at,
                   json.dumps(j.result) if j.result is not None else None, j.error))

    def recent_jobs(self, limit: int = 20) -> list[dict]:
        cols = ["job_id", "kind", "status", "progress", "total", "started_at", "finished_at", "result", "error"]
        rows = self.db.q(f"select {', '.join(cols)} from stc.jobs order by started_at desc limit %s", (limit,))
        return [dict(zip(cols, r)) for r in rows]


# ------------------------------------------------------------------------------------------------
# Watchlist in Postgres
# ------------------------------------------------------------------------------------------------

def _entry(row) -> WatchlistEntry:
    uid, name, ptype, aliases, programs, dobs, countries, ids, remarks, source = row
    return WatchlistEntry(uid=uid, name=name, party_type=ptype, aliases=list(aliases or []), programs=list(programs or []),
                          dobs=list(dobs or []), countries=list(countries or []), id_numbers=list(ids or []),
                          remarks=remarks, source=source)


class PgWatchlist:
    """Watchlist facade over stc.watchlist_entries. Metadata lives in kv 'list_meta'."""

    def __init__(self, db: PgDB):
        self.db = db
        self._sample: Optional[list[WatchlistEntry]] = None
        self.reload_meta()

    def reload_meta(self) -> None:
        r = self.db.q("select v from stc.kv where k='list_meta'")
        meta = json.loads(r[0][0]) if r else {}
        self.source = meta.get("source", "none loaded")
        self.version = meta.get("version", "none")
        self.datasets = meta.get("datasets", [])
        self.attribution = meta.get("attribution", "")
        self._len = int(meta.get("entities", 0))
        self._sample = None

    def __len__(self) -> int:
        return self._len

    def get(self, uid: str) -> Optional[WatchlistEntry]:
        r = self.db.q(f"select {ENTRY_COLS} from stc.watchlist_entries where uid=%s", (uid,))
        return _entry(r[0]) if r else None

    def get_many(self, uids: list[str]) -> list[WatchlistEntry]:
        if not uids:
            return []
        return [_entry(r) for r in self.db.q(f"select {ENTRY_COLS} from stc.watchlist_entries where uid = any(%s)", (uids,))]

    @property
    def entries(self) -> list[WatchlistEntry]:
        """A random sample (used for demo scenarios and planting synthetic matches, never for screening)."""
        if self._sample is None:
            self._sample = [_entry(r) for r in self.db.q(
                f"select {ENTRY_COLS} from stc.watchlist_entries order by random() limit 4000")]
        return self._sample


class PgScreener:
    def __init__(self, db: PgDB, threshold: float = 85.0, max_candidates: int = 5, pool_limit: int = 4000):
        self.db = db
        self.threshold = threshold
        self.max_candidates = max_candidates
        self.pool_limit = pool_limit

    def screen(self, party: Party) -> list[Candidate]:
        is_org = party.party_type in ORG_TYPES
        variants = [normalize_name(party.name, is_entity=is_org)]
        if party.party_type == PartyType.unknown:
            alt = normalize_name(party.name, is_entity=True)
            if alt.text != variants[0].text:
                variants.append(alt)
        best: dict[str, tuple[float, str, WatchlistEntry]] = {}
        for v in variants:
            core = [(t, p) for t, p in zip(v.core_tokens, v.phonetic) if len(t) >= 2]
            if not core:
                continue
            need = 1 if len(core) == 1 else 2
            per_token = [["p:" + p, "t:" + t[:3]] for t, p in core]
            all_keys = sorted({k for ks in per_token for k in ks})
            cond = " + ".join(["(n.block_keys && %s::text[])::int"] * len(per_token))
            sql = (f"select n.display, {', '.join('e.' + c.strip() for c in ENTRY_COLS.split(','))} "
                   f"from stc.watchlist_names n join stc.watchlist_entries e on e.uid = n.uid "
                   f"where n.block_keys && %s::text[] and ({cond}) >= %s limit %s")
            rows = self.db.q(sql, (all_keys, *per_token, need, self.pool_limit))
            for row in rows:
                display, entry = row[0], _entry(row[1:])
                org = entry.party_type in ORG_TYPES
                qv = normalize_name(party.name, is_entity=True) if org and not is_org else v
                s = name_score(qv, normalize_name(display, is_entity=org))
                prev = best.get(entry.uid)
                if prev is None or s > prev[0]:
                    best[entry.uid] = (s, display, entry)
        hits = sorted((b for b in best.values() if b[0] >= self.threshold), key=lambda b: -b[0])[: self.max_candidates]
        return [Candidate(entry=e, matched_name=d, name_score=s, signals=compute_signals(party, e)) for s, d, e in hits]


def sync_watchlist(db: PgDB, wl: Watchlist) -> dict:
    """Make stc.watchlist_* equal to `wl` in one transaction; return the delta vs what was stored."""
    t0 = time.perf_counter()
    stored = dict(db.q("select uid, fingerprint from stc.watchlist_entries"))
    new_fp = {e.uid: entry_fingerprint(e) for e in wl.entries}
    added = [u for u in new_fp if u not in stored]
    changed = [u for u in new_fp if u in stored and stored[u] != new_fp[u]]
    removed = [u for u in stored if u not in new_fp]
    write = set(added) | set(changed)
    by_uid = {e.uid: e for e in wl.entries}
    with db.tx() as cur:
        if changed or removed:
            cur.execute("delete from stc.watchlist_entries where uid = any(%s)", (changed + removed,))
        if write:
            with cur.copy(f"copy stc.watchlist_entries ({ENTRY_COLS}, fingerprint) from stdin") as cp:
                for u in write:
                    e = by_uid[u]
                    cp.write_row((e.uid, e.name, e.party_type.value, e.aliases, e.programs, e.dobs, e.countries,
                                  e.id_numbers, e.remarks, e.source, new_fp[u]))
            with cur.copy("copy stc.watchlist_names (uid, display, block_keys) from stdin") as cp:
                for u in write:
                    e = by_uid[u]
                    org = e.party_type in ORG_TYPES
                    for display in dict.fromkeys([e.name, *e.aliases]):
                        n = normalize_name(display, is_entity=org)
                        keys = sorted(Screener._block_keys(n))
                        if keys:
                            cp.write_row((u, display, keys))
        meta = {"source": wl.source, "version": wl.version, "datasets": wl.datasets, "attribution": wl.attribution,
                "entities": len(wl), "synced_at": utcnow()}
        cur.execute("insert into stc.kv(k, v) values ('list_meta', %s) on conflict (k) do update set v=excluded.v",
                    (json.dumps(meta, default=str),))
    return {"added": added, "changed": changed, "removed": len(removed), "baseline": not stored,
            "seconds": round(time.perf_counter() - t0, 1)}
