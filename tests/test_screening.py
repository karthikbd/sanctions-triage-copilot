from pathlib import Path

import pytest

from sanctions_copilot.matcher import Screener, name_score
from sanctions_copilot.models import Party, SignalOutcome
from sanctions_copilot.normalize import normalize_name, parse_dob
from sanctions_copilot.watchlist import load_ofac_dir, load_sample, parse_remarks

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("a,b", [
    ("Mohammed Al-Rashid", "Muhammad Al Rashid"),
    ("Aleksandr Petrov", "Alexander Petrov"),
    ("Zhang Wei", "Wei Zhang"),
    ("Youssef Haddad", "Yusuf Hadad"),
    ("Kim Jong Chol", "Kim Jong-chol"),
])
def test_transliteration_and_order_score_high(a, b):
    assert name_score(normalize_name(a), normalize_name(b)) >= 90


def test_unrelated_names_score_low():
    assert name_score(normalize_name("Emily Carter"), normalize_name("Irina Volkova")) < 60


def test_single_token_is_capped():
    assert name_score(normalize_name("Petrov"), normalize_name("Aleksandr Petrov")) <= 80


def test_legal_forms_are_ignored_for_entities():
    a = normalize_name("Golden Crescent Trading L.L.C.", is_entity=True)
    b = normalize_name("GOLDEN CRESCENT TRADING LLC", is_entity=True)
    assert a.sorted_text == b.sorted_text


@pytest.mark.parametrize("raw,ymin,ymax,exact", [
    ("1971", 1971, 1971, False), ("1971-03-12", 1971, 1971, True), ("12/03/1971", 1971, 1971, True),
    ("12 Mar 1971", 1971, 1971, True), ("1969 to 1972", 1969, 1972, False), ("circa 1970", 1969, 1971, False),
])
def test_parse_dob(raw, ymin, ymax, exact):
    d = parse_dob(raw)
    assert (d.year_min, d.year_max, d.exact is not None) == (ymin, ymax, exact)


def test_screen_finds_alias_and_computes_signals():
    s = Screener(load_sample().entries)
    [c] = s.screen(Party(name="Muhammad Said al-Rashidi", party_type="individual", dob="1968-02-14"))
    assert c.entry.uid == "S-1001"
    assert c.signals.dob == SignalOutcome.exact


def test_dob_transposition_is_near_not_mismatch():
    s = Screener(load_sample().entries)
    [c] = s.screen(Party(name="Aleksandr Petrovsky", party_type="individual", dob="11/03/1971"))
    assert c.signals.dob == SignalOutcome.near


def test_clean_name_has_no_hits():
    assert Screener(load_sample().entries).screen(Party(name="Sophie Martin")) == []


def test_ofac_csv_parser():
    wl = load_ofac_dir(FIX)
    assert len(wl) == 3
    person = wl.get("OFAC-9001")
    assert person.party_type.value == "individual"
    assert person.dobs == ["04 Mar 1966", "1967"]
    assert "A7712093" in person.id_numbers
    assert "QARAMANLY, Tareq" in person.aliases
    assert {"Iraq"} <= set(person.countries)
    assert person.programs == ["SDGT", "IRGC"]
    vessel = wl.get("OFAC-9003")
    assert vessel.party_type.value == "vessel"
    assert "IMO 9412277" in vessel.id_numbers
    assert "Panama" in vessel.countries
    assert wl.get("OFAC-9002").party_type.value == "entity"


def test_parse_remarks_handles_empty():
    assert parse_remarks("") == ([], [], [])


def test_ofac_screening_end_to_end():
    s = Screener(load_ofac_dir(FIX).entries)
    [c] = s.screen(Party(name="Tareq Qaramanly", party_type="individual", dob="1966-03-04"))
    assert c.entry.uid == "OFAC-9001" and c.signals.dob == SignalOutcome.exact
