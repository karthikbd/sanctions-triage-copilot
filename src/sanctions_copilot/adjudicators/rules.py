"""Deterministic baseline adjudicator.

This is what many banks run today in some form: a transparent decision table over
secondary identifiers. It is the baseline the LLM adjudicator is evaluated against,
and the fallback whenever the LLM is unavailable or returns something invalid.
"""

from __future__ import annotations

from ..models import Candidate, Decision, Evidence, Party, PartyType, SignalOutcome as S, Verdict
from ..signals import ORG_TYPES


def evidence_from_signals(c: Candidate) -> list[Evidence]:
    s = c.signals
    ev = [Evidence(factor="name", assessment="supports_match" if c.name_score >= 95 else "neutral",
                   detail=f"name similarity {c.name_score} ('{c.matched_name}')")]

    def add(factor: str, outcome: S, detail: str) -> None:
        if outcome in (S.exact, S.match):
            a = "supports_match"
        elif outcome == S.mismatch:
            a = "contradicts_match"
        elif outcome == S.missing:
            a = "missing"
        else:
            a = "neutral"
        ev.append(Evidence(factor=factor, assessment=a, detail=detail))

    add("date_of_birth", s.dob, s.dob_detail)
    add("country", s.country, s.country_detail)
    add("id_number", s.id_number, s.id_detail)
    add("party_type", s.party_type, s.party_type_detail)
    return ev


class RulesAdjudicator:
    name = "rules-v1"

    def adjudicate(self, party: Party, candidate: Candidate) -> Decision:
        s, score = candidate.signals, candidate.name_score
        ev = evidence_from_signals(candidate)

        def d(verdict: Verdict, conf: float, why: str) -> Decision:
            return Decision(verdict=verdict, confidence=conf, rationale=why, evidence=ev, adjudicator=self.name)

        if s.id_number == S.exact:
            return d(Verdict.true_match, 0.99, "An identifier on the customer record matches the listed party.")
        if s.party_type == S.mismatch:
            listed = candidate.entry.party_type
            if PartyType.individual in (party.party_type, listed) and (party.party_type in {PartyType.vessel, PartyType.aircraft} or listed in {PartyType.vessel, PartyType.aircraft}):
                return d(Verdict.false_positive, 0.95, f"Party type conflict: {s.party_type_detail}.")
            return d(Verdict.false_positive, 0.70,
                     f"Party type conflict ({s.party_type_detail}), but an entity can be owned or controlled "
                     "by a listed individual; check ownership before clearing.")
        if s.dob == S.mismatch:
            return d(Verdict.false_positive, 0.93, f"{s.dob_detail}.")
        if s.dob == S.exact:
            if score >= 88:
                return d(Verdict.true_match, 0.95, f"Strong name similarity ({score}) and {s.dob_detail}.")
            return d(Verdict.escalate, 0.6, f"DOB matches but name similarity is moderate ({score}).")
        if s.dob in (S.match, S.near):
            if s.country == S.mismatch:
                return d(Verdict.escalate, 0.55, f"{s.dob_detail}, but {s.country_detail}.")
            if score >= 90:
                return d(Verdict.true_match, 0.8, f"Name similarity {score} and {s.dob_detail}.")
            return d(Verdict.escalate, 0.6, f"{s.dob_detail}; name similarity {score}.")
        # No usable DOB on at least one side.
        if s.country == S.match and score >= 92 and (party.party_type in ORG_TYPES or candidate.entry.party_type in ORG_TYPES):
            return d(Verdict.true_match, 0.75, f"Organisation name similarity {score} and {s.country_detail}.")
        if s.country == S.mismatch:
            return d(Verdict.false_positive, 0.65,
                     f"No DOB to compare; {s.country_detail}. Country alone is not sufficient to clear.")
        return d(Verdict.escalate, 0.5, f"Name similarity {score} with insufficient secondary identifiers to decide.")
