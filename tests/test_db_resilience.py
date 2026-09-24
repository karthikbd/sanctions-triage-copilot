"""A bad database setting must never take the site down or leak the password."""
from fastapi.testclient import TestClient

from sanctions_copilot.api import create_app
from sanctions_copilot.pg_url import DatabaseURLError, clean_db_url, describe_db_url
from sanctions_copilot.service import Settings, TriageService


def test_clean_db_url_repairs_common_paste_mistakes():
    u = clean_db_url(" postgres://postgres.ref:qw#er@ty@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
                     "?sslmode=require&supa=base-pooler.x ")
    assert u == ("postgres://postgres.ref:qw%23er%40ty@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
                 "?sslmode=require")
    assert "pgbouncer" not in clean_db_url("postgresql://u:p@h.pooler.supabase.com:6543/postgres?pgbouncer=true")
    assert clean_db_url("postgresql://u:[pw]@h.supabase.com:6543/postgres").startswith("postgresql://u:pw@")
    assert describe_db_url("postgresql://u:secret@h:6543/postgres") == "u@h:6543/postgres"
    for bad in ("", "postgresql://u:[YOUR-PASSWORD]@h:6543/postgres", "host=h user=u"):
        try:
            clean_db_url(bad)
            raise AssertionError(bad)
        except DatabaseURLError:
            pass


def test_unreachable_database_falls_back_to_demo(monkeypatch, tmp_path):
    for k in ("STC_DATABASE_URL", "DATABASE_URL", "POSTGRES_URL", "POSTGRES_URL_NON_POOLING"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("POSTGRES_URL", "postgres://postgres.ref:TopSecret#1@127.0.0.1:1/postgres?supa=base-pooler.x")
    monkeypatch.setenv("STC_SERVERLESS", "1")
    s = Settings(watchlist="sample", db_path=str(tmp_path / "x.db"), customers_path=str(tmp_path / "c.csv"))
    svc = TriageService.from_settings(s)
    assert svc.db is None and svc.backend == "sqlite"
    c = TestClient(create_app(svc, start_scheduler=False))
    h = c.get("/api/health").json()
    assert h["backend"] == "sqlite" and h["list_status"] == "db_error"
    assert "POSTGRES_URL" in h["db_error"] and "TopSecret" not in h["db_error"]
    assert c.post("/api/screen", json={"name": "Nobody Special"}).status_code == 200
