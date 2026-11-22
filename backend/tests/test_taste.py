import pytest

from app.pantry import Pantry
from app.taste import forecast, verdict


def rows(**kw):
    return {r.taste: r for r in forecast(**kw)}


def test_salt_fraction_drives_saltiness():
    # Dal: 8 g salt is the recipe's ideal for 1 kg of dal.
    r = rows(added={"salt": 8}, ideal_grams={"salt": 8}, mass_g=1000)["salty"]
    assert r.verdict == "just right" and r.score == 5.0 and r.concentration == pytest.approx(0.008)
    assert rows(added={"salt": 12}, ideal_grams={"salt": 8}, mass_g=1000)["salty"].verdict == "too salty"
    assert rows(added={"salt": 5}, ideal_grams={"salt": 8}, mass_g=1000)["salty"].verdict == "bland"
    # Same 12 g in a double batch (2 kg) is fine: it's concentration, not grams.
    assert rows(added={"salt": 12}, ideal_grams={"salt": 16}, mass_g=2000)["salty"].level == "low"


def test_profile_factor_moves_the_ideal():
    mild = rows(added={"chili": 3}, ideal_grams={"chili": 3}, mass_g=1000, factors={"chili": 0.5})["heat"]
    assert mild.verdict in ("spicy", "too spicy")


def test_soda_and_turmeric_only_flag_excess():
    r = rows(added={"baking_soda": 1}, ideal_grams={}, mass_g=700)
    assert r["soapy"].verdict == "fine"
    assert rows(added={"baking_soda": 8}, ideal_grams={}, mass_g=700)["soapy"].level == "high"


def test_verdict_bands():
    assert verdict("salty", 1.0) == ("just right", "ok")
    assert verdict("salty", 1.25)[1] == "high" and verdict("salty", 0.8)[1] == "low"


def test_rating_learns_profile():
    p = Pantry()
    pid = p.active_profile
    before = p.profiles[pid].factor("salt")
    p.learn_from_rating(pid, {"salty": "too much", "heat": "right"})
    assert p.profiles[pid].factor("salt") == pytest.approx(before * 0.9, abs=1e-3)
    assert p.profiles[pid].factor("chili") == 1.0
