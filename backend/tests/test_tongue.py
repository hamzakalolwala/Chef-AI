import numpy as np
import pytest

from app.tongue import (Stimulus, Taster, hill, liking, panel_verdict, perceive, random_taster, stimulus,
                        taster_for)

DAL = {"salt": 8, "turmeric": 1.5, "chili": 2, "cumin": 2, "ghee": 12}


def test_receptor_curve_is_monotonic_and_saturates():
    xs = [hill(c, 150, 1.4) for c in (0, 30, 75, 150, 300, 1200, 10000)]
    assert xs == sorted(xs) and xs[3] == pytest.approx(0.5) and xs[-1] > 0.99 and xs[0] == 0


def test_dal_chemistry_is_realistic():
    s = stimulus(DAL, 1000, "dal")
    assert 150 < s.salty < 200          # 8 g salt in 0.8 L water ≈ 171 mM ≈ 1 % brine
    assert 10 < s.heat < 20             # mild: ≈ 12 µM capsaicin
    assert s.fat == pytest.approx(12)   # 12 g ghee per kg


def test_mixture_interactions():
    t = Taster()
    bitter = Stimulus(bitter=4.0)
    assert perceive(t, Stimulus(bitter=4.0, sweet=300))["bitter"] < perceive(t, bitter)["bitter"]   # sugar masks
    assert perceive(t, Stimulus(bitter=4.0, salty=150))["bitter"] < perceive(t, bitter)["bitter"]   # salt masks
    assert perceive(t, Stimulus(salty=150, umami=12))["salty"] > perceive(t, Stimulus(salty=150))["salty"]
    assert perceive(t, Stimulus(heat=40, fat=80))["heat"] < perceive(t, Stimulus(heat=40))["heat"]  # ghee calms chili


def test_bitter_supertaster_tastes_more_bitter():
    s = Stimulus(bitter=2.5)
    sup = Taster(sensitivity={"bitter": 0.45}, bitter_type="super")
    non = Taster(sensitivity={"bitter": 2.2}, bitter_type="non")
    assert perceive(sup, s)["bitter"] > 2 * perceive(non, s)["bitter"]


def test_liking_peaks_at_the_recipe_and_names_the_problem():
    ideal = stimulus(DAL, 1000, "dal")
    me = taster_for("me", ideal)
    just_right, _, _ = liking(me, perceive(me, ideal))
    salty, why, _ = liking(me, perceive(me, stimulus({**DAL, "salt": 16}, 1000, "dal")))
    bland, why2, _ = liking(me, perceive(me, stimulus({**DAL, "salt": 3}, 1000, "dal")))
    assert just_right > 9.5 and salty < 6 and why == "too salty" and why2 == "needs salt"


def test_less_salt_person_dislikes_the_standard_dal():
    std = stimulus(DAL, 1000, "dal")
    mild = taster_for("mild", stimulus({**DAL, "salt": 5.6, "chili": 1}, 1000, "dal"))
    score, why, _ = liking(mild, perceive(mild, std))
    assert score < 8 and why in ("too salty", "too spicy")


def test_panel_prefers_the_recipe_over_double_salt():
    ideal = stimulus(DAL, 1000, "dal")
    good = panel_verdict(ideal, ideal, n=60)
    bad = panel_verdict(stimulus({**DAL, "salt": 16}, 1000, "dal"), ideal, n=60)
    assert good["mean"] > bad["mean"] + 2 and good["liked_%"] > 70
    assert next(iter(bad["complaints"])) == "too salty"


def test_population_varies():
    rng = np.random.default_rng(1)
    ideal = stimulus(DAL, 1000, "dal")
    types = [random_taster(rng, ideal).bitter_type for _ in range(400)]
    assert 0.18 < types.count("super") / 400 < 0.32 and 0.18 < types.count("non") / 400 < 0.32


def test_sour_and_baking_soda():
    s = stimulus({"x_lemon_juice": 15}, 600, "poha", names={"x_lemon_juice": "Lemon juice"})
    assert s.sour > 5
    soda = stimulus({"flour": 160, "butter": 114, "baking_soda": 10}, 700)
    t = Taster()
    assert perceive(t, soda)["bitter"] > perceive(t, stimulus({"flour": 160, "baking_soda": 2.75}, 700))["bitter"]


def test_tracker_reports_family_liking():
    from app.dishes import load_catalog
    from app.pantry import Pantry
    from app.tracker import Tracker
    from tests.test_tracker import Clock, dal_probs, run
    p = Pantry()
    p.active_profile = "me"
    c = Clock()
    tr = Tracker(load_catalog(), clock=c, pantry=p)
    tr.set_burners([{"id": "b1", "name": "Front", "zone": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}}])
    run(tr, c, 5, flame=0.9, probs=dal_probs())
    for ing, g in {"salt": 8, "turmeric": 1.5, "chili": 2, "cumin": 2, "ghee": 12}.items():
        tr.add_ingredient("b1", ing, g)
    tongue = tr.snapshot()[0]["session"]["tongue"]
    fam = {f["id"]: f for f in tongue["family"]}
    assert fam["me"]["liking"] > 9 and fam["mild"]["liking"] < fam["me"]["liking"]
    assert fam["mild"]["complaint"] in ("too salty", "too spicy")
    assert tongue["intensity"]["now"]["salty"] > 4
