"""FastAPI app: screening API, analyst workbench UI, list refresh scheduler and customer-book jobs."""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from importlib import resources
from pathlib import Path
from typing import Optional

import hmac
import json

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .models import Alert, AnalystReview, Party, ScreeningResult
from .service import TriageService

log = logging.getLogger(__name__)


class Health(BaseModel):
    status: str
    adjudicator: str
    list_source: str
    list_size: int
    list_version: str
    list_status: str
    backend: str = "sqlite"
    serverless: bool = False
    admin_required: bool = False
    db_target: Optional[str] = None
    db_error: Optional[str] = None
    ui: str = "legacy"


class GenerateRequest(BaseModel):
    n: int = Field(2000, ge=50, le=50_000)
    use_sdv: bool = True
    seed: int = 42


def _scheduler(svc: TriageService, stop: threading.Event) -> None:
    """Initial OpenSanctions load, then a refresh every STC_REFRESH_HOURS (OpenSanctions publishes several times a day)."""
    hours = svc.settings.refresh_hours
    first = True
    while not stop.is_set():
        if first or hours > 0:
            try:
                svc.start_job("list_refresh", lambda job: svc.refresh_lists(job=job))
            except Exception:
                log.exception("scheduled refresh failed to start")
        first = False
        if hours <= 0:
            return
        stop.wait(hours * 3600)


def create_app(service: Optional[TriageService] = None, start_scheduler: Optional[bool] = None) -> FastAPI:
    svc = service or TriageService.from_settings()
    st = svc.settings
    run_sched = start_scheduler if start_scheduler is not None else (
        st.watchlist.startswith("opensanctions") and not st.serverless)
    admin_required = bool(st.admin_passcode) or st.serverless

    def require_admin(x_admin_passcode: str = Header("", alias="X-Admin-Passcode")):
        """Admin actions need the passcode. Locally with no passcode set they are open; on a serverless
        deployment with no passcode set they are disabled rather than left open."""
        if not admin_required:
            return
        if not st.admin_passcode:
            raise HTTPException(403, "Admin actions are disabled: set STC_ADMIN_PASSCODE on the deployment")
        if not hmac.compare_digest(x_admin_passcode.encode(), st.admin_passcode.encode()):
            raise HTTPException(401, "Admin passcode required")

    def require_cron(authorization: str = Header("")):
        if not st.cron_secret or not hmac.compare_digest(authorization.encode(), f"Bearer {st.cron_secret}".encode()):
            raise HTTPException(401, "cron secret required")
    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(_app):
        if run_sched:
            threading.Thread(target=_scheduler, args=(svc, stop), daemon=True, name="list-scheduler").start()
        yield
        stop.set()

    app = FastAPI(
        title="Sanctions Triage Copilot",
        version="0.2.0",
        description="Sanctions screening with LLM-assisted alert triage, deterministic guardrails and a tamper-evident audit trail.",
        lifespan=lifespan,
    )
    app.state.service = svc

    # UI: the React app built into src/sanctions_copilot/webui (npm run build in web/), served by FastAPI locally,
    # in Docker and on Vercel. Falls back to the single-file legacy page when it hasn't been built.
    web_dir = Path(os.getenv("STC_WEB_DIR") or Path(__file__).resolve().parent / "webui")
    react_index = web_dir / "index.html"
    if (web_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=web_dir / "assets"), name="assets")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def ui() -> str:
        if react_index.is_file():
            return react_index.read_text(encoding="utf-8")
        return resources.files("sanctions_copilot.static").joinpath("index.html").read_text(encoding="utf-8")

    @app.get("/legacy", response_class=HTMLResponse, include_in_schema=False)
    def legacy_ui() -> str:
        return resources.files("sanctions_copilot.static").joinpath("index.html").read_text(encoding="utf-8")

    @app.get("/api/health", response_model=Health)
    def health():
        wl = svc.watchlist
        return Health(status="ok", adjudicator=svc.adjudicator.name, list_source=wl.source, list_size=len(wl),
                      list_version=wl.version, list_status=svc.list_state["status"], backend=svc.backend,
                      serverless=st.serverless, admin_required=admin_required,
                      db_target=svc.db_info.get("target"),
                      db_error=(svc.db_info.get("errors") or [None])[-1] if svc.db is None else None,
                      ui="react" if react_index.is_file() else "legacy")

    @app.get("/api/admin/check", dependencies=[Depends(require_admin)])
    def admin_check():
        return {"ok": True}

    # -- screening ------------------------------------------------------------------------------
    @app.post("/api/screen", response_model=ScreeningResult)
    def screen(party: Party):
        return svc.screen(party, actor="api")

    @app.post("/api/screen/batch", response_model=list[ScreeningResult])
    def screen_batch(parties: list[Party]):
        if len(parties) > 500:
            raise HTTPException(413, "Batch limited to 500 parties per request; use the customer book for more")
        return [svc.screen(p, actor="api-batch", origin="batch") for p in parties]

    # -- alerts ---------------------------------------------------------------------------------
    @app.get("/api/alerts", response_model=list[Alert])
    def list_alerts(status: Optional[str] = Query(None), limit: int = Query(200, le=2000)):
        return svc.store.list_alerts(status=status, limit=limit)

    @app.get("/api/alerts/{alert_id}", response_model=Alert)
    def get_alert(alert_id: str):
        a = svc.store.get_alert(alert_id)
        if not a:
            raise HTTPException(404, "alert not found")
        return a

    @app.post("/api/alerts/{alert_id}/review", response_model=Alert, dependencies=[Depends(require_admin)])
    def review(alert_id: str, body: AnalystReview):
        try:
            return svc.review(alert_id, body)
        except KeyError:
            raise HTTPException(404, "alert not found")

    @app.get("/api/alerts/{alert_id}/audit")
    def alert_audit(alert_id: str):
        return svc.store.audit_trail(ref=alert_id)

    @app.post("/api/admin/reset-queue", dependencies=[Depends(require_admin)])
    def reset_queue():
        if not svc.settings.allow_reset:
            raise HTTPException(403, "Queue reset is disabled (STC_ALLOW_RESET=false)")
        return {"removed": svc.reset_queue(actor="ui"), "note": "Alerts removed; the audit log keeps the history."}

    # -- watchlists -----------------------------------------------------------------------------
    @app.get("/api/lists")
    def lists():
        wl = svc.watchlist
        state = dict(svc.list_state)
        if svc.db is not None:  # other serverless instances may have refreshed: read shared state
            state["last_refresh"] = svc.store.kv_get("last_list_check") or state.get("last_refresh")
            ld = svc.store.kv_get("last_delta")
            state["last_delta"] = json.loads(ld) if ld else state.get("last_delta")
        return {"source": wl.source, "version": wl.version, "entities": len(wl), "datasets": wl.datasets,
                "attribution": wl.attribution, "configured": st.watchlist, "backend": svc.backend,
                "refresh_hours": st.refresh_hours, "schedule": "Vercel cron (daily) + GitHub Actions (6-hourly)" if st.serverless
                else f"every {st.refresh_hours} h", **state}

    @app.get("/api/scenarios")
    def scenarios():
        from .service import build_scenarios

        return build_scenarios(svc.watchlist)

    @app.post("/api/lists/refresh", dependencies=[Depends(require_admin)])
    def refresh(force: bool = False):
        job = svc.start_job("list_refresh", lambda j: svc.refresh_lists(force=force, job=j))
        return asdict(job)

    # -- customer book --------------------------------------------------------------------------
    @app.get("/api/customers")
    def customers(limit: int = Query(25, le=500)):
        labels = [l_["label"] for l_ in svc.labels.values()]
        last = svc.store.kv_get("last_batch")
        import json as _json

        return {"path": svc.settings.customers_path, "count": len(svc.customers),
                "planted_true_matches": labels.count("true_match"), "planted_near_misses": labels.count("near_miss"),
                "sample": svc.customers[:limit], "last_batch": _json.loads(last) if last else None}

    @app.post("/api/customers/generate", dependencies=[Depends(require_admin)])
    def generate(body: GenerateRequest):
        if st.serverless and body.n > st.max_customers_inline:
            raise HTTPException(413, f"On serverless, generate at most {st.max_customers_inline} customers here; "
                                     "use the GitHub Actions worker (SDV) for larger books")
        job = svc.start_job("generate_customers", lambda j: svc.generate_customers(body.n, body.use_sdv, body.seed))
        return asdict(job)

    @app.post("/api/customers/screen", dependencies=[Depends(require_admin)])
    def screen_book():
        svc.load_customer_book()
        if not svc.customers:
            raise HTTPException(409, "No customer book yet. Generate one first.")
        job = svc.start_job("screen_customers", lambda j: svc.screen_customer_book(job=j))
        return asdict(job)

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        j = svc.jobs.get(job_id)
        if not j:
            raise HTTPException(404, "job not found")
        return asdict(j)

    @app.get("/api/jobs")
    def jobs():
        if hasattr(svc.store, "recent_jobs"):
            return svc.store.recent_jobs()
        return [asdict(j) for j in sorted(svc.jobs.values(), key=lambda j: j.started_at, reverse=True)[:20]]

    # -- scheduled work (Vercel Cron sends "Authorization: Bearer $CRON_SECRET") --------------------
    @app.get("/api/cron/daily", dependencies=[Depends(require_cron)])
    def cron_daily():
        out = {"refresh": None, "queue_reset": None}
        try:
            out["refresh"] = svc.refresh_lists()
        except Exception as e:
            out["refresh"] = {"error": f"{type(e).__name__}: {e}"}
        if os.getenv("STC_NIGHTLY_RESET", "false").lower() == "true":
            out["queue_reset"] = svc.reset_queue(actor="nightly-cron")
        return json.loads(json.dumps(out, default=str))

    # -- metrics & audit ------------------------------------------------------------------------
    @app.get("/api/metrics")
    def metrics():
        return svc.metrics()

    @app.get("/api/audit/verify")
    def verify():
        return svc.store.verify_audit()

    return app


def factory() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
