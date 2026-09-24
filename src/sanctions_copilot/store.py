"""SQLite persistence for alerts plus a hash-chained, append-only audit log.

Each audit record stores sha256(prev_hash + canonical_json(record)). Editing or deleting any
past record breaks the chain, which `verify_audit()` detects. This gives examiners a simple
way to confirm the decision history was not altered after the fact.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from typing import Any, Optional

from .models import Alert, AlertStatus, utcnow

GENESIS = "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
  alert_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL,
  priority TEXT NOT NULL,
  body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_alerts_status ON alerts(status);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,
  event TEXT NOT NULL,
  ref TEXT,
  payload TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL
);
"""


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class Store:
    def __init__(self, path: str = ":memory:"):
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(_SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(alerts)")}
        if "dedupe_key" not in cols:  # migrate databases created by v0.1
            self.db.execute("ALTER TABLE alerts ADD COLUMN dedupe_key TEXT")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_alerts_dedupe ON alerts(dedupe_key)")
        self.db.commit()

    # -- alerts -----------------------------------------------------------------------------
    def save_alert(self, a: Alert) -> None:
        with self._lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO alerts(alert_id, request_id, created_at, status, priority, body, dedupe_key) VALUES (?,?,?,?,?,?,?)",
                (a.alert_id, a.request_id, a.created_at, a.status.value, a.priority.value, a.model_dump_json(), a.dedupe_key),
            )

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        row = self.db.execute("SELECT body FROM alerts WHERE alert_id=?", (alert_id,)).fetchone()
        return Alert.model_validate_json(row[0]) if row else None

    def find_by_dedupe_key(self, key: str) -> Optional[Alert]:
        row = self.db.execute(
            "SELECT body FROM alerts WHERE dedupe_key=? ORDER BY created_at DESC LIMIT 1", (key,)).fetchone()
        return Alert.model_validate_json(row[0]) if row else None

    def clear_alerts(self) -> int:
        with self._lock, self.db:
            n = self.db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
            self.db.execute("DELETE FROM alerts")
            return n

    def kv_get(self, k: str) -> Optional[str]:
        row = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return row[0] if row else None

    def kv_set(self, k: str, v: str) -> None:
        with self._lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO kv(k, v) VALUES (?,?)", (k, v))

    def list_alerts(self, status: Optional[str] = None, limit: int = 200) -> list[Alert]:
        order = "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, created_at DESC"
        if status:
            rows = self.db.execute(f"SELECT body FROM alerts WHERE status=? ORDER BY {order} LIMIT ?", (status, limit))
        else:
            rows = self.db.execute(f"SELECT body FROM alerts ORDER BY {order} LIMIT ?", (limit,))
        return [Alert.model_validate_json(r[0]) for r in rows.fetchall()]

    def count_by_origin(self) -> dict[str, int]:
        rows = self.db.execute(
            "SELECT COALESCE(json_extract(body, '$.origin'), 'screening'), COUNT(*) FROM alerts GROUP BY 1").fetchall()
        return {k: v for k, v in rows}

    def review_stats(self) -> tuple[int, int]:
        row = self.db.execute(
            "SELECT COUNT(*), SUM(json_extract(body, '$.review.outcome') = json_extract(body, '$.decision.verdict')) "
            "FROM alerts WHERE json_extract(body, '$.review') IS NOT NULL").fetchone()
        return int(row[0] or 0), int(row[1] or 0)

    def counts(self) -> dict[str, int]:
        rows = self.db.execute("SELECT status, COUNT(*) FROM alerts GROUP BY status").fetchall()
        out = {s.value: 0 for s in AlertStatus}
        out.update({k: v for k, v in rows})
        return out

    # -- audit ------------------------------------------------------------------------------
    def audit(self, actor: str, event: str, ref: Optional[str], payload: dict) -> str:
        with self._lock, self.db:
            row = self.db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row[0] if row else GENESIS
            ts = utcnow()
            body = {"ts": ts, "actor": actor, "event": event, "ref": ref, "payload": payload}
            h = hashlib.sha256((prev + _canon(body)).encode()).hexdigest()
            self.db.execute(
                "INSERT INTO audit(ts, actor, event, ref, payload, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
                (ts, actor, event, ref, _canon(payload), prev, h),
            )
            return h

    def audit_trail(self, ref: Optional[str] = None, limit: int = 500) -> list[dict]:
        q = "SELECT seq, ts, actor, event, ref, payload, prev_hash, hash FROM audit"
        args: tuple = ()
        if ref:
            q += " WHERE ref=?"
            args = (ref,)
        q += " ORDER BY seq LIMIT ?"
        rows = self.db.execute(q, (*args, limit)).fetchall()
        return [
            {"seq": r[0], "ts": r[1], "actor": r[2], "event": r[3], "ref": r[4], "payload": json.loads(r[5]),
             "prev_hash": r[6], "hash": r[7]}
            for r in rows
        ]

    def verify_audit(self) -> dict:
        prev = GENESIS
        n = 0
        for seq, ts, actor, event, ref, payload, prev_hash, h in self.db.execute(
            "SELECT seq, ts, actor, event, ref, payload, prev_hash, hash FROM audit ORDER BY seq"
        ):
            body = {"ts": ts, "actor": actor, "event": event, "ref": ref, "payload": json.loads(payload)}
            expect = hashlib.sha256((prev + _canon(body)).encode()).hexdigest()
            if prev_hash != prev or h != expect:
                return {"valid": False, "records": n, "broken_at_seq": seq}
            prev = h
            n += 1
        return {"valid": True, "records": n, "head": prev}
