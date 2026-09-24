"""Name screening: blocking index + fuzzy/phonetic scoring.

Design goals, in priority order:
1. Recall. A missed true hit is a regulatory breach; an extra alert is only cost.
2. Explainability. Every score can be decomposed for an auditor.
3. Speed. The full OFAC SDN list (~18k entries, ~20k aliases) screens in milliseconds.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from .models import Candidate, Party, PartyType, WatchlistEntry
from .normalize import NormName, normalize_name
from .signals import ORG_TYPES, compute_signals


@dataclass
class _IndexedName:
    entry_idx: int
    display: str
    norm: NormName


def _token_similarity(a: str, b: str, pa: str, pb: str) -> float:
    if a == b:
        return 1.0
    if pa and pa == pb and a[0] == b[0]:
        return 0.95
    return JaroWinkler.similarity(a, b)


def _coverage(q: NormName, c: NormName) -> tuple[float, float]:
    """Best-alignment token similarity. Returns (avg similarity over shorter name, length ratio)."""
    qa = list(zip(q.core_tokens, q.phonetic))
    ca = list(zip(c.core_tokens, c.phonetic))
    if not qa or not ca:
        return 0.0, 0.0
    short, long_ = (qa, ca) if len(qa) <= len(ca) else (ca, qa)
    used: set[int] = set()
    total = 0.0
    for tok, ph in short:
        best, best_j = 0.0, -1
        for j, (t2, p2) in enumerate(long_):
            if j in used:
                continue
            s = _token_similarity(tok, t2, ph, p2)
            if s > best:
                best, best_j = s, j
        if best_j >= 0:
            used.add(best_j)
        total += best
    return total / len(short), len(short) / len(long_)


def name_score(q: NormName, c: NormName) -> float:
    """0-100 similarity that is order-insensitive, transliteration-tolerant and penalises partial names."""
    if not q.tokens or not c.tokens:
        return 0.0
    if q.sorted_text == c.sorted_text:
        return 100.0
    sort_ratio = fuzz.token_sort_ratio(q.text, c.text)
    jw = JaroWinkler.similarity(q.sorted_text, c.sorted_text) * 100
    align, length_ratio = _coverage(q, c)
    # Token alignment is the most robust signal; penalise when one name has extra tokens
    # ("Ali Hassan" vs "Ali Hassan Mahmoud Al-Tikriti") but only moderately, because
    # customers often omit middle names.
    aligned = align * 100 * (0.80 + 0.20 * length_ratio)
    score = max(sort_ratio, 0.92 * jw, aligned)
    # Single-token names are dangerous in both directions; cap them unless exact.
    if min(len(q.core_tokens), len(c.core_tokens)) == 1 and q.text != c.text:
        score = min(score, 80.0)
    return round(score, 1)


class Screener:
    def __init__(self, entries: list[WatchlistEntry], threshold: float = 85.0, max_candidates: int = 5):
        self.entries = entries
        self.threshold = threshold
        self.max_candidates = max_candidates
        self._names: list[_IndexedName] = []
        self._blocks: dict[str, set[int]] = defaultdict(set)
        for i, e in enumerate(entries):
            is_org = e.party_type in ORG_TYPES
            for display in [e.name, *e.aliases]:
                n = normalize_name(display, is_entity=is_org)
                if not n.tokens:
                    continue
                k = len(self._names)
                self._names.append(_IndexedName(i, display, n))
                for key in self._block_keys(n):
                    self._blocks[key].add(k)

    @staticmethod
    def _block_keys(n: NormName) -> set[str]:
        keys = set()
        for tok, ph in zip(n.core_tokens, n.phonetic):
            if len(tok) < 2:
                continue
            keys.add("p:" + ph)
            keys.add("t:" + tok[:3])
        return keys

    def _pool(self, v: NormName) -> list[int]:
        """Names sharing a block key with at least two distinct query tokens (one for single-token queries).

        Single-token comparisons are capped below the alert threshold in name_score, so requiring two
        aligned tokens for multi-token queries removes only pairs that could never alert, while cutting
        the number of names scored by an order of magnitude on large lists.
        """
        core = [(t, p) for t, p in zip(v.core_tokens, v.phonetic) if len(t) >= 2]
        if not core:
            return []
        need = 1 if len(core) == 1 else 2
        counts: dict[int, int] = defaultdict(int)
        empty: set[int] = set()
        for tok, ph in core:
            for k in self._blocks.get("p:" + ph, empty) | self._blocks.get("t:" + tok[:3], empty):
                counts[k] += 1
        return [k for k, c in counts.items() if c >= need]

    def screen(self, party: Party) -> list[Candidate]:
        is_org = party.party_type in ORG_TYPES
        q = normalize_name(party.name, is_entity=is_org)
        # For unknown types also try the legal-form-stripped version.
        variants = [q]
        if party.party_type == PartyType.unknown:
            alt = normalize_name(party.name, is_entity=True)
            if alt.text != q.text:
                variants.append(alt)

        best_per_entry: dict[int, tuple[float, str]] = {}
        for v in variants:
            for k in self._pool(v):
                ix = self._names[k]
                # Compare like with like: strip legal forms from the query when the list side is an org.
                qv = v
                if self.entries[ix.entry_idx].party_type in ORG_TYPES and not is_org:
                    qv = normalize_name(party.name, is_entity=True)
                s = name_score(qv, ix.norm)
                prev = best_per_entry.get(ix.entry_idx)
                if prev is None or s > prev[0]:
                    best_per_entry[ix.entry_idx] = (s, ix.display)

        hits = [(i, s, disp) for i, (s, disp) in best_per_entry.items() if s >= self.threshold]
        hits.sort(key=lambda t: -t[1])
        out = []
        for i, s, disp in hits[: self.max_candidates]:
            e = self.entries[i]
            out.append(Candidate(entry=e, matched_name=disp, name_score=s, signals=compute_signals(party, e)))
        return out
