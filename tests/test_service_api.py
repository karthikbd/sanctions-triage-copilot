from fastapi.testclient import TestClient

from sanctions_copilot.api import create_app
from sanctions_copilot.models import AnalystReview, Party, Verdict


def test_screen_review_and_audit_chain(service):
    res = service.screen(Party(name="Irina Volkova", party_type="individual", dob="1982-04-18"))
    [a] = res.alerts
    assert a.decision.verdict == Verdict.true_match
    service.review(a.alert_id, AnalystReview(analyst="jdoe", outcome=Verdict.true_match, comment="Confirmed, DOB and name"))
    assert service.store.get_alert(a.alert_id).status.value == "confirmed_match"
    assert service.store.verify_audit()["valid"]
    m = service.metrics()
    assert m["analyst_model_agreement"] == 1.0


def test_audit_tampering_is_detected(service):
    service.screen(Party(name="Kim Min-jun", party_type="individual", dob="1995"))
    service.store.db.execute("UPDATE audit SET payload='{\"verdict\":\"true_match\"}' WHERE seq=1")
    v = service.store.verify_audit()
    assert not v["valid"] and v["broken_at_seq"] == 1


def test_api_endpoints(service):
    client = TestClient(create_app(service))
    assert client.get("/api/health").json()["status"] == "ok"
    r = client.post("/api/screen", json={"name": "Kim Min-jun", "party_type": "individual", "dob": "1995-08-14"})
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "auto_closed"
    aid = body["alerts"][0]["alert_id"]
    assert client.get(f"/api/alerts/{aid}").json()["alert_id"] == aid
    r = client.post(f"/api/alerts/{aid}/review", json={"analyst": "qa", "outcome": "false_positive", "comment": "QA sample ok"})
    assert r.json()["status"] == "cleared"
    assert client.get("/api/alerts/ALR-NOPE").status_code == 404
    assert client.get("/api/audit/verify").json()["valid"]
    assert client.get("/").status_code == 200
    batch = client.post("/api/screen/batch", json=[{"name": "Emily Carter"}, {"name": "Irina Volkova", "dob": "1982"}]).json()
    assert [b["outcome"] for b in batch] == ["clear", "review"]
    assert client.post("/api/screen", json={"name": ""}).status_code == 422


def test_admin_passcode_and_cron_secret():
    from sanctions_copilot.service import Settings, TriageService
    from sanctions_copilot.store import Store
    from sanctions_copilot.watchlist import load_sample

    s = Settings(watchlist="sample", db_path=":memory:", database_url="", serverless=True,
                 admin_passcode="s3cret-pass", cron_secret="cron-token")
    client = TestClient(create_app(TriageService(load_sample(), store=Store(":memory:"), settings=s)))
    aid = client.post("/api/screen", json={"name": "Irina Volkova", "dob": "1982"}).json()["alerts"][0]["alert_id"]
    body = {"analyst": "a", "outcome": "true_match", "comment": ""}
    assert client.post(f"/api/alerts/{aid}/review", json=body).status_code == 401
    assert client.post(f"/api/alerts/{aid}/review", json=body, headers={"X-Admin-Passcode": "wrong"}).status_code == 401
    assert client.post(f"/api/alerts/{aid}/review", json=body, headers={"X-Admin-Passcode": "s3cret-pass"}).status_code == 200
    assert client.get("/api/cron/daily").status_code == 401
    r = client.get("/api/cron/daily", headers={"Authorization": "Bearer cron-token"})
    assert r.status_code == 200 and r.json()["queue_reset"] is None  # alerts persist unless STC_NIGHTLY_RESET=true
