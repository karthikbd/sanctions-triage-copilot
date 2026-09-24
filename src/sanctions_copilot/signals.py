"""Deterministic comparison of secondary identifiers (DOB, country, ID numbers, party type).

These signals are computed in code so that the facts an alert is closed on can be
reproduced exactly by an auditor. The LLM reasons over them; it does not produce them.
"""

from __future__ import annotations

from .models import Party, PartyType, SignalOutcome, Signals, WatchlistEntry
from .normalize import country_name, normalize_country, normalize_id, parse_dob

ORG_TYPES = {PartyType.entity, PartyType.vessel, PartyType.aircraft}


def compare_dob(party: Party, entry: WatchlistEntry) -> tuple[SignalOutcome, str]:
    p = parse_dob(party.dob)
    listed = [d for d in (parse_dob(x) for x in entry.dobs) if d]
    if not p or not listed:
        return SignalOutcome.missing, "DOB not available on both sides"
    best = SignalOutcome.mismatch
    detail = f"customer {party.dob} vs listed {', '.join(entry.dobs)}"
    for d in listed:
        if p.exact and d.exact:
            if p.exact == d.exact:
                return SignalOutcome.exact, f"exact DOB match ({party.dob})"
            # Day/month transposition is a common data-entry error (03/04 vs 04/03).
            if (p.exact.year == d.exact.year and p.exact.month == d.exact.day and p.exact.day == d.exact.month):
                return SignalOutcome.near, f"day/month transposed: {party.dob} vs {d.raw}"
            if p.exact.year == d.exact.year:
                best = _better(best, SignalOutcome.near)
                continue
        overlap = p.year_min <= d.year_max and d.year_min <= p.year_max
        if overlap:
            best = _better(best, SignalOutcome.match)
            continue
        gap = min(abs(p.year_min - d.year_max), abs(d.year_min - p.year_max))
        if gap <= 1:
            best = _better(best, SignalOutcome.near)
    if best == SignalOutcome.match:
        detail = f"birth year consistent: {party.dob} vs listed {', '.join(entry.dobs)}"
    elif best == SignalOutcome.near:
        detail = f"DOB close but not equal: {party.dob} vs listed {', '.join(entry.dobs)}"
    else:
        detail = f"DOB conflict: {party.dob} vs listed {', '.join(entry.dobs)}"
    return best, detail


_RANK = {SignalOutcome.mismatch: 0, SignalOutcome.near: 1, SignalOutcome.match: 2, SignalOutcome.exact: 3}


def _better(a: SignalOutcome, b: SignalOutcome) -> SignalOutcome:
    return a if _RANK.get(a, 0) >= _RANK.get(b, 0) else b


def compare_country(party: Party, entry: WatchlistEntry) -> tuple[SignalOutcome, str]:
    mine = {c for c in (normalize_country(party.country), normalize_country(party.nationality)) if c}
    theirs = {c for c in (normalize_country(x) for x in entry.countries) if c}
    if not mine or not theirs:
        return SignalOutcome.missing, "country not available on both sides"
    both = mine & theirs
    if both:
        return SignalOutcome.match, f"country overlap: {_names(both)}"
    return SignalOutcome.mismatch, f"customer {_names(mine)} vs listed {_names(theirs)}"


def _names(codes: set[str]) -> str:
    return ", ".join(sorted(country_name(c) for c in codes))


def compare_ids(party: Party, entry: WatchlistEntry) -> tuple[SignalOutcome, str]:
    mine = {normalize_id(x) for x in party.id_numbers if normalize_id(x)}
    theirs = {normalize_id(x) for x in entry.id_numbers if normalize_id(x)}
    if not mine or not theirs:
        return SignalOutcome.missing, "no ID numbers on both sides"
    hit = mine & theirs
    if hit:
        return SignalOutcome.exact, f"identifier match: {', '.join(sorted(hit))}"
    # Different ID numbers are not proof of a different person (different document types),
    # so we report them as 'unknown' rather than 'mismatch'.
    return SignalOutcome.unknown, "ID numbers present but none in common (may be different document types)"


def compare_type(party: Party, entry: WatchlistEntry) -> tuple[SignalOutcome, str]:
    a, b = party.party_type, entry.party_type
    if PartyType.unknown in (a, b):
        return SignalOutcome.unknown, "party type not known on both sides"
    if a == b:
        return SignalOutcome.match, f"both {a.value}"
    if a in ORG_TYPES and b in ORG_TYPES:
        return SignalOutcome.unknown, f"{a.value} vs {b.value} (related organisation types)"
    return SignalOutcome.mismatch, f"customer is {a.value}, listed party is {b.value}"


def compute_signals(party: Party, entry: WatchlistEntry) -> Signals:
    dob, dob_d = compare_dob(party, entry)
    cty, cty_d = compare_country(party, entry)
    idn, idn_d = compare_ids(party, entry)
    typ, typ_d = compare_type(party, entry)
    return Signals(
        dob=dob, dob_detail=dob_d,
        country=cty, country_detail=cty_d,
        id_number=idn, id_detail=idn_d,
        party_type=typ, party_type_detail=typ_d,
    )
