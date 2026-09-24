"""Postgres backend tests against a throwaway local Postgres (pgserver). Skipped when unavailable."""

import os
from pathlib import Path

import httpx
import pytest

pgserver = pytest.importorskip("pgserver")
pytest.importorskip("psycopg")

from sanctions_copilot.models import AnalystReview, Party, Verdict  # noqa: E402
from sanctions_copilot.pg import PgDB, PgScreener, PgStore, PgWatchlist, sync_watchlist  # noqa: E402
from sanctions_copilot.matcher import Screener  # noqa: E402
from sanctions_copilot.service import Settings, TriageService  # noqa: E402
from sanctions_copilot.watchlist import load_opensanctions, load_sample  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="module")
def pg_url(tmp_path_factory):
    srv = pgserver.get_server(str(tmp_path_factory.mktemp("pg")), cleanup_mode="stop")
    url = srv.get_uri()
    db = PgDB(url)
    db.q("drop schema if exists stc cascade")
    db.q("do $$ begin create role anon; exception when duplicate_object then null; end $$")
    db.q("do $$ begin create role authenticated; exception when duplicate_object then null; end $$")
    sql = next((ROOT / "supabase" / "migrations").glob("*_stc_initial_schema.sql")).read_text()
    with db.conn().cursor() as cur:
        cur.execute(sql)
    yield url
    srv.cleanup()


@pytest.fixture
def db(pg_url):
    d = PgDB(pg_url)
    for t in ("alerts", "audit", "kv", "customers", "jobs", "watchlist_names", "watchlist_entries"):
        d.q(f"truncate stc.{t} cascade")
    return d


def test_sql_screener_matches_in_memory_screener(db):
    wl = load_sample()
    delta = sync_watchlist(db, wl)
    assert delta["baseline"] and len(delta["added"]) == len(wl)
    mem, sql = Screener(wl.entries), PgScreener(db)
    parties = [Party(name="Muhammad Said al-Rashidi", party_type="individual", dob="1968-02-14"),
               Party(name="Kim Min-jun", dob="1995"), Party(name="Golden Crescent Trading L.L.C.", party_type="entity"),
               Party(name="Chol Nam Ri"), Party(name="Emily Carter"), Party(name="M/T Ocean Pearl", party_type="vessel")]
    for p in parties:
        a = [(c.entry.uid, c.name_score) for c in mem.screen(p)]
        b = [(c.entry.uid, c.name_score) for c in sql.screen(p)]
        assert a == b, p.name


def test_store_audit_dedupe_and_tamper_detection(db):
    sync_watchlist(db, load_sample())
    s = Settings(watchlist="sample", database_url="set", serverless=False)
    svc = TriageService(PgWatchlist(db), store=PgStore(db), settings=s, screener=PgScreener(db), db=db)
    p = Party(name="Irina Volkova", party_type="individual", dob="1982-04-18")
    a = svc.screen(p).alerts[0]
    assert svc.screen(p).repeat_hits[0].alert_id == a.alert_id
    svc.review(a.alert_id, AnalystReview(analyst="qa", outcome=Verdict.true_match, comment="ok"))
    assert svc.screen(p).outcome == "blocked"
    m = svc.metrics()
    assert m["by_status"]["confirmed_match"] == 1 and m["analyst_model_agreement"] == 1.0
    assert svc.store.verify_audit()["valid"]
    db.q("update stc.audit set payload = '{}' where seq = (select min(seq) from stc.audit)")
    assert not svc.store.verify_audit()["valid"]


def _client(ver, body):
    def h(req):
        u = str(req.url)
        if u.endswith("/index.json"):
            return httpx.Response(200, json={"version": ver, "resources": [{"name": "targets.simple.csv", "url": f"https://x/{ver}/targets.simple.csv"}]})
        return httpx.Response(200, text=body)
    return httpx.Client(transport=httpx.MockTransport(h))


def test_refresh_sync_delta_and_customer_rescreen(db, tmp_path):
    v1 = (FIX / "os_targets_v1.simple.csv").read_text()
    v2 = v1 + "NK-fff666,Person,Viktor Arkadyevich Belousov,Viktor Belousov,1971-11-12,ru,,,UK,,,GB-RUS,gb_fcdo_sanctions,2026-09-23,2026-09-23,2026-09-23\n"
    s = Settings(watchlist="opensanctions:us_ofac_sdn", database_url="set", serverless=True)
    svc = TriageService(load_sample(), store=PgStore(db), settings=s, db=db)
    first = svc.refresh_lists(loader=lambda: load_opensanctions(["us_ofac_sdn"], cache_dir=str(tmp_path), client=_client("v1", v1)))
    assert first["baseline"] and first["entities"] == 4
    svc.store.replace_customers([{"customer_id": "C1", "name": "Viktor Belousov", "party_type": "individual", "dob": "1971-11-12",
                                  "country": "RU", "nationality": "RU", "id_numbers": ""}], {})
    svc.load_customer_book()
    second = svc.refresh_lists(loader=lambda: load_opensanctions(["us_ofac_sdn"], cache_dir=str(tmp_path), client=_client("v2", v2)))
    assert second["added"] == 1 and second["rescreen"]["new_alerts"] == 1
    assert svc.store.list_alerts()[0].origin == "list_update"
    assert int(db.q("select count(*) from stc.watchlist_entries")[0][0]) == 5
    # a fresh "serverless instance" sees the synced list
    fresh = TriageService.from_postgres(Settings(watchlist="opensanctions", database_url=db.url, serverless=True))
    assert len(fresh.watchlist) == 5 and fresh.screen(Party(name="Tareq Qaramanly", dob="1966-03-04")).alerts


def test_customer_generation_roundtrip(db):
    sync_watchlist(db, load_sample())
    s = Settings(watchlist="sample", database_url="set", serverless=True)
    svc = TriageService(PgWatchlist(db), store=PgStore(db), settings=s, screener=PgScreener(db), db=db)
    rep = svc.generate_customers(200, use_sdv=False, seed=1)
    assert len(svc.customers) == 200 and rep["planted_true_matches"] >= 5
    stats = svc.screen_customer_book()
    assert stats["planted_found"] == stats["planted_found_not_auto_closed"]
    job = svc.start_job("noop", lambda j: {"ok": True})
    assert job.status == "done" and svc.store.recent_jobs()[0]["job_id"] == job.job_id
