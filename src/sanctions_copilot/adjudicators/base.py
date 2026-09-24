from __future__ import annotations

from typing import Protocol

from ..models import Candidate, Decision, Party


class Adjudicator(Protocol):
    """Turns (party, candidate) into a recommended disposition. Policy decides what happens next."""

    name: str

    def adjudicate(self, party: Party, candidate: Candidate) -> Decision: ...
