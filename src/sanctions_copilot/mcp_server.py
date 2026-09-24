"""MCP server: lets an analyst work the alert queue from Claude Desktop or any MCP client.

Run:  stc mcp        (stdio transport)
Tools: screen_party, list_open_alerts, get_alert, record_review, queue_metrics, verify_audit_log.
"""

from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from .models import AnalystReview, Party, Verdict
from .service import TriageService

mcp = FastMCP("sanctions-triage-copilot")
_svc: Optional[TriageService] = None


def svc() -> TriageService:
    global _svc
    if _svc is None:
        _svc = TriageService.from_settings()
    return _svc


def _brief(a) -> dict:
    return {
        "alert_id": a.alert_id, "status": a.status.value, "priority": a.priority.value,
        "customer": a.party.name, "listed_party": a.candidate.entry.name, "list_uid": a.candidate.entry.uid,
        "programs": a.candidate.entry.programs, "name_score": a.candidate.name_score,
        "recommendation": a.decision.verdict.value, "confidence": a.decision.confidence,
    }


@mcp.tool()
def screen_party(name: str, party_type: str = "unknown", dob: Optional[str] = None, country: Optional[str] = None,
                 nationality: Optional[str] = None, id_numbers: Optional[list[str]] = None,
                 reference: Optional[str] = None, notes: Optional[str] = None) -> dict:
    """Screen a person, company or vessel against the configured sanctions list and triage any alerts."""
    p = Party(name=name, party_type=party_type, dob=dob, country=country, nationality=nationality,
              id_numbers=id_numbers or [], reference=reference, notes=notes)
    r = svc().screen(p, actor="mcp")
    return {"request_id": r.request_id, "outcome": r.outcome, "list": f"{r.list_source} ({r.list_size} entries)",
            "alerts": [_brief(a) | {"rationale": a.decision.rationale, "policy": a.policy_notes} for a in r.alerts]}


@mcp.tool()
def list_open_alerts(limit: int = 20) -> list[dict]:
    """List alerts awaiting human review, highest priority first."""
    return [_brief(a) for a in svc().store.list_alerts(status="pending_review", limit=limit)]


@mcp.tool()
def get_alert(alert_id: str) -> dict:
    """Full detail of one alert: customer record, list entry, deterministic signals, recommendation, audit trail."""
    a = svc().store.get_alert(alert_id)
    if not a:
        return {"error": f"alert {alert_id} not found"}
    return a.model_dump(mode="json") | {"audit_trail": svc().store.audit_trail(ref=alert_id)}


@mcp.tool()
def record_review(alert_id: str, analyst: str, outcome: str, comment: str) -> dict:
    """Record a human analyst's disposition. outcome: true_match | false_positive | escalate.
    Only call this when the human analyst has explicitly stated their decision."""
    a = svc().review(alert_id, AnalystReview(analyst=analyst, outcome=Verdict(outcome), comment=comment))
    return _brief(a) | {"review": a.review.model_dump(mode="json")}


@mcp.tool()
def queue_metrics() -> dict:
    """Queue size by status, auto-close rate and analyst/model agreement."""
    return svc().metrics()


@mcp.tool()
def verify_audit_log() -> dict:
    """Verify the hash chain of the audit log (detects any edited or deleted record)."""
    return svc().store.verify_audit()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
