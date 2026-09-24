"""Guardrail policy: the only component allowed to decide an alert's status.

Principle: an adjudicator (rules or LLM) *recommends*; policy *decides*. Policy is small,
deterministic and unit-tested so it can be documented for model risk management (SR 11-7)
and reviewed by compliance without reading prompts.

Rules
1. A true match is never closed automatically. It goes to a human with high priority.
2. An alert may be auto-closed as a false positive only when ALL hold:
   - the recommendation is false_positive with confidence >= AUTO_CLOSE_CONFIDENCE
   - a *hard* contradiction was found by deterministic code (DOB conflict, or individual vs vessel/aircraft)
   - no identifier matched
   - no prompt-injection indicators were found in the party's free-text fields
3. An identifier match overrides any recommendation to true_match.
4. Anything else goes to a human, prioritised by the recommendation.
"""

from __future__ import annotations

import re

from .models import AlertStatus, Candidate, Decision, Party, PartyType, Priority, SignalOutcome as S, Verdict

AUTO_CLOSE_CONFIDENCE = 0.85

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|rules|guidance)",
    r"(mark|classify|treat|close|clear|dispose)\s+(this|the|it)?\s*(alert|case|match|hit|customer|payment|party)?\s*(as)?\s*(a\s+)?(false[\s-]*positive|cleared|not\s+a\s+match|no\s+match)",
    r"\b(system|developer)\s*(prompt|message|override)\b",
    r"\byou\s+are\s+now\b",
    r"\bpre[\s-]*(cleared|approved|screened)\b",
    r"do\s+not\s+(escalate|flag|alert|report)",
    r"</?\s*(system|instructions?|assistant|tool)\s*>",
    r"\bassistant\s*:",
    r"record_decision",
]
_INJECTION_RE = [re.compile(p, re.I) for p in _INJECTION_PATTERNS]


def detect_injection(party: Party) -> list[str]:
    text = " ".join(x for x in (party.notes, party.address, party.name, party.reference) if x)
    return [m.group(0)[:80] for rx in _INJECTION_RE if (m := rx.search(text))]


def hard_contradictions(party: Party, c: Candidate) -> list[str]:
    out = []
    if c.signals.dob == S.mismatch:
        out.append(f"DOB conflict ({c.signals.dob_detail})")
    if c.signals.party_type == S.mismatch:
        kinds = {party.party_type, c.entry.party_type}
        if PartyType.individual in kinds and kinds & {PartyType.vessel, PartyType.aircraft}:
            out.append(f"party type conflict ({c.signals.party_type_detail})")
    return out


def apply_policy(party: Party, c: Candidate, d: Decision, injection_flags: list[str]) -> tuple[AlertStatus, Priority, list[str], Decision]:
    notes: list[str] = []

    if c.signals.id_number == S.exact and d.verdict != Verdict.true_match:
        notes.append(f"Override: identifier match ({c.signals.id_detail}) forces true_match (was {d.verdict.value}).")
        d = d.model_copy(update={"verdict": Verdict.true_match, "confidence": max(d.confidence, 0.99)})

    if injection_flags or d.suspected_injection:
        notes.append("Possible prompt injection in free-text fields; auto-closure disabled and case flagged.")
        return AlertStatus.pending_review, Priority.high, notes, d

    if d.verdict == Verdict.true_match:
        notes.append("Recommended true match: route to L2 for confirmation, blocking/rejection and regulatory reporting.")
        return AlertStatus.pending_review, Priority.high, notes, d

    if d.verdict == Verdict.false_positive:
        hard = hard_contradictions(party, c)
        if d.confidence >= AUTO_CLOSE_CONFIDENCE and hard:
            notes.append("Auto-closed as false positive on deterministic evidence: " + "; ".join(hard) + ". Eligible for QA sampling.")
            return AlertStatus.auto_closed, Priority.low, notes, d
        if not hard:
            notes.append("Recommended false positive but no hard contradicting identifier: human review required.")
        else:
            notes.append(f"Confidence {d.confidence:.2f} below auto-close threshold {AUTO_CLOSE_CONFIDENCE}.")
        return AlertStatus.pending_review, Priority.low, notes, d

    notes.append("Insufficient evidence to decide: human review required.")
    return AlertStatus.pending_review, Priority.medium, notes, d
