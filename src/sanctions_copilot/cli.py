"""Command line: `stc serve | screen | screen-file | load-ofac | mcp`."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from .models import Party


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines); real environment variables win."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if v.strip() and k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip().strip('"').strip("'")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stc", description="Sanctions Triage Copilot")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="Run the API and analyst UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    one = sub.add_parser("screen", help="Screen one party and print the result as JSON")
    one.add_argument("name")
    one.add_argument("--type", default="unknown", dest="party_type")
    one.add_argument("--dob")
    one.add_argument("--country")
    one.add_argument("--id", action="append", default=[], dest="ids")

    f = sub.add_parser("screen-file", help="Batch-screen a CSV (columns: name, party_type, dob, country, nationality, id_numbers, reference)")
    f.add_argument("csv_path")
    f.add_argument("--out", default="screening_results.csv")

    o = sub.add_parser("load-ofac", help="Download the current OFAC SDN list (public CSV)")
    o.add_argument("--dest", default="data/ofac")

    r = sub.add_parser("refresh-lists", help="Download/refresh OpenSanctions datasets into data/opensanctions")
    r.add_argument("--datasets", default="us_ofac_sdn,un_sc_sanctions,eu_fsf,gb_fcdo_sanctions")
    r.add_argument("--force", action="store_true")

    g = sub.add_parser("synth", help="Generate a synthetic customer book (SDV + Faker) with planted list hits")
    g.add_argument("--n", type=int, default=2000)
    g.add_argument("--no-sdv", action="store_true")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--screen", action="store_true", help="Also batch-screen the generated book and print metrics")

    sub.add_parser("mcp", help="Run the MCP server on stdio")

    w = sub.add_parser("worker", help="Heavy jobs against the configured database (used by Docker / GitHub Actions)")
    w.add_argument("task", choices=["refresh", "synth", "screen-book", "reset-queue", "status"])
    w.add_argument("--n", type=int, default=5000)
    w.add_argument("--no-sdv", action="store_true")
    w.add_argument("--screen", action="store_true", help="synth: also screen the new book")
    w.add_argument("--force", action="store_true", help="refresh: re-sync even if versions are unchanged")

    a = ap.parse_args(argv)
    load_dotenv()

    if a.cmd == "serve":
        import uvicorn

        uvicorn.run("sanctions_copilot.api:factory", factory=True, host=a.host, port=a.port)
        return 0
    if a.cmd == "mcp":
        from .mcp_server import main as mcp_main

        mcp_main()
        return 0
    if a.cmd == "load-ofac":
        from .watchlist import download_ofac, load_ofac_dir

        dest = download_ofac(a.dest)
        wl = load_ofac_dir(dest)
        print(f"Downloaded {len(wl)} SDN entries to {dest}. Use: STC_WATCHLIST={dest} stc serve")
        return 0

    if a.cmd == "refresh-lists":
        from .watchlist import load_opensanctions

        wl = load_opensanctions([d.strip() for d in a.datasets.split(",") if d.strip()], force=a.force)
        for d in wl.datasets:
            print(f"{d['name']:<22} {d['entities']:>7,} entities  version {d['version']}  ({d['source']}){'  ERROR ' + d['error'] if d.get('error') else ''}")
        print(f"Total {len(wl):,} entries. {wl.attribution}")
        return 0

    from .service import Settings, TriageService

    if a.cmd == "worker":
        return _worker(a)

    if a.cmd == "synth":
        s = Settings()
        svc = TriageService.from_settings(s)
        if s.watchlist.startswith("opensanctions"):
            print("Loading OpenSanctions lists...")
            svc.refresh_lists()
        rep = svc.generate_customers(a.n, use_sdv=not a.no_sdv, seed=a.seed)
        print(json.dumps(rep, indent=2))
        if a.screen:
            print(json.dumps(svc.screen_customer_book(), indent=2))
        return 0

    svc = TriageService.from_settings()
    if a.cmd == "screen":
        r = svc.screen(Party(name=a.name, party_type=a.party_type, dob=a.dob, country=a.country, id_numbers=a.ids), actor="cli")
        print(json.dumps(r.model_dump(mode="json"), indent=2))
        return 0
    if a.cmd == "screen-file":
        rows_out = []
        with open(a.csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                ids = [x.strip() for x in (row.get("id_numbers") or "").split(";") if x.strip()]
                p = Party(name=row["name"], party_type=row.get("party_type") or "unknown", dob=row.get("dob") or None,
                          country=row.get("country") or None, nationality=row.get("nationality") or None,
                          id_numbers=ids, reference=row.get("reference") or None)
                r = svc.screen(p, actor="batch")
                top = r.alerts[0] if r.alerts else None
                rows_out.append({
                    "reference": p.reference or "", "name": p.name, "outcome": r.outcome, "alerts": len(r.alerts),
                    "top_list_uid": top.candidate.entry.uid if top else "", "top_list_name": top.candidate.entry.name if top else "",
                    "top_score": top.candidate.name_score if top else "", "recommendation": top.decision.verdict.value if top else "",
                    "priority": top.priority.value if top else "", "request_id": r.request_id,
                })
        with open(a.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()) if rows_out else ["name"])
            w.writeheader()
            w.writerows(rows_out)
        summary = {k: sum(1 for r in rows_out if r["outcome"] == k) for k in ("clear", "auto_closed", "review")}
        print(f"Screened {len(rows_out)} parties -> {a.out}  {summary}")
        return 0
    return 1


def _worker(a) -> int:
    import logging

    from .service import Settings, TriageService

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = Settings()
    s.serverless = True  # run jobs inline and persist them to the jobs table
    if not s.database_url:
        print("worker: STC_DATABASE_URL is not set; running against local SQLite", file=sys.stderr)
    svc = TriageService.from_settings(s)

    def show(job):
        print(json.dumps({"job": job.job_id, "kind": job.kind, "status": job.status, "error": job.error,
                          "result": job.result}, indent=2, default=str))
        return 0 if job.status == "done" else 1

    if a.task == "status":
        print(json.dumps({"backend": s.backend, "list": svc.watchlist.source, "entries": len(svc.watchlist),
                          "version": svc.watchlist.version, "customers": len(svc.customers),
                          "alerts": svc.store.counts()}, indent=2))
        return 0
    if a.task == "refresh":
        return show(svc.start_job("list_refresh", lambda j: svc.refresh_lists(force=a.force, job=j)))
    if a.task == "synth":
        if s.watchlist.startswith("opensanctions") and len(svc.watchlist) < 1000:
            show(svc.start_job("list_refresh", lambda j: svc.refresh_lists(job=j)))
        rc = show(svc.start_job("generate_customers", lambda j: svc.generate_customers(a.n, use_sdv=not a.no_sdv)))
        if rc == 0 and a.screen:
            rc = show(svc.start_job("screen_customers", lambda j: svc.screen_customer_book(job=j)))
        return rc
    if a.task == "screen-book":
        return show(svc.start_job("screen_customers", lambda j: svc.screen_customer_book(job=j)))
    if a.task == "reset-queue":
        print(json.dumps({"removed": svc.reset_queue(actor="worker")}))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
