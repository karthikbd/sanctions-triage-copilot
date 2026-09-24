"""Domain models shared by the screening engine, adjudicators, API and evals."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PartyType(str, Enum):
    individual = "individual"
    entity = "entity"
    vessel = "vessel"
    aircraft = "aircraft"
    unknown = "unknown"


class Party(BaseModel):
    """A customer, counterparty or payment party submitted for screening."""

    name: str = Field(..., min_length=1, max_length=300)
    party_type: PartyType = PartyType.unknown
    dob: Optional[str] = Field(None, description="Date of birth: YYYY, YYYY-MM-DD or '12 Mar 1971'")
    country: Optional[str] = Field(None, description="Country of residence / incorporation / flag")
    nationality: Optional[str] = None
    id_numbers: list[str] = Field(default_factory=list, description="Passport, national ID, IMO, registration no.")
    address: Optional[str] = None
    reference: Optional[str] = Field(None, description="Customer or payment reference in the source system")
    notes: Optional[str] = Field(
        None,
        max_length=4000,
        description="Free text from the source system (KYC notes, payment remittance info). Treated as untrusted.",
    )


class WatchlistEntry(BaseModel):
    uid: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    party_type: PartyType = PartyType.unknown
    programs: list[str] = Field(default_factory=list)
    dobs: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    id_numbers: list[str] = Field(default_factory=list)
    remarks: Optional[str] = None
    source: str = "SAMPLE"


class SignalOutcome(str, Enum):
    exact = "exact"
    match = "match"
    near = "near"
    mismatch = "mismatch"
    missing = "missing"
    unknown = "unknown"


class Signals(BaseModel):
    """Deterministic comparison of secondary identifiers. Computed in code, never by the LLM."""

    dob: SignalOutcome = SignalOutcome.missing
    dob_detail: str = ""
    country: SignalOutcome = SignalOutcome.missing
    country_detail: str = ""
    id_number: SignalOutcome = SignalOutcome.missing
    id_detail: str = ""
    party_type: SignalOutcome = SignalOutcome.unknown
    party_type_detail: str = ""


class Candidate(BaseModel):
    entry: WatchlistEntry
    matched_name: str
    name_score: float
    signals: Signals


class Verdict(str, Enum):
    true_match = "true_match"
    false_positive = "false_positive"
    escalate = "escalate"


class Evidence(BaseModel):
    factor: str
    assessment: str = Field(..., description="supports_match | contradicts_match | neutral | missing")
    detail: str


class Decision(BaseModel):
    verdict: Verdict
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    evidence: list[Evidence] = Field(default_factory=list)
    adjudicator: str
    next_steps: list[str] = Field(default_factory=list)
    suspected_injection: bool = False
    notes: list[str] = Field(default_factory=list)
    latency_ms: Optional[float] = None


class AlertStatus(str, Enum):
    auto_closed = "auto_closed"          # closed as false positive by policy, sampled for QA
    pending_review = "pending_review"    # needs a human analyst
    confirmed_match = "confirmed_match"  # analyst confirmed true match
    cleared = "cleared"                  # analyst cleared as false positive


class Priority(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class AnalystReview(BaseModel):
    analyst: str = Field(..., min_length=1, max_length=100)
    outcome: Verdict
    comment: str = Field("", max_length=4000)
    reviewed_at: str = Field(default_factory=utcnow)


class Alert(BaseModel):
    alert_id: str
    request_id: str
    dedupe_key: str = ""
    origin: str = Field("screening", description="screening | batch | list_update")
    created_at: str = Field(default_factory=utcnow)
    party: Party
    candidate: Candidate
    decision: Decision
    status: AlertStatus
    priority: Priority
    policy_notes: list[str] = Field(default_factory=list)
    injection_flags: list[str] = Field(default_factory=list)
    review: Optional[AnalystReview] = None


class RepeatHit(BaseModel):
    """A hit that matched an alert we already hold for the same party + same list entry version."""

    alert_id: str
    list_uid: str
    list_name: str
    previous_status: AlertStatus
    action: str = Field(..., description="linked_to_open_alert | suppressed_previously_cleared | still_confirmed")
    detail: str


class ScreeningResult(BaseModel):
    request_id: str
    screened_at: str = Field(default_factory=utcnow)
    party: Party
    list_source: str
    list_size: int
    alerts: list[Alert] = Field(default_factory=list, description="alerts created by this request")
    repeat_hits: list[RepeatHit] = Field(default_factory=list, description="hits already covered by an existing alert")
    injection_flags: list[str] = Field(default_factory=list)
    duration_ms: float

    @computed_field  # type: ignore[prop-decorator]
    @property
    def outcome(self) -> str:
        if any(r.action == "still_confirmed" for r in self.repeat_hits) or any(
                a.status == AlertStatus.confirmed_match for a in self.alerts):
            return "blocked"
        if any(a.status == AlertStatus.pending_review for a in self.alerts) or any(
                r.action == "linked_to_open_alert" for r in self.repeat_hits):
            return "review"
        if self.alerts:
            return "auto_closed"
        if self.repeat_hits:
            return "suppressed"
        return "clear"
