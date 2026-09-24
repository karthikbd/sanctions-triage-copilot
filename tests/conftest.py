import pytest

from sanctions_copilot.adjudicators import RulesAdjudicator
from sanctions_copilot.service import TriageService
from sanctions_copilot.store import Store
from sanctions_copilot.watchlist import load_sample


@pytest.fixture
def service():
    return TriageService(load_sample(), adjudicator=RulesAdjudicator(), store=Store(":memory:"))
