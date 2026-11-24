import pytest

from app.cookchem import ChaiRecipe, TadkaRecipe, simulate_chai, simulate_tadka
from app.heat import SOURCES, VESSELS, Pot, time_to_boil
from app.pantry import Pantry
from app.recipe_lab import evaluate_chai, improve

HABIT = ChaiRecipe(tea_g=8, tea_boil_s=300, milk_simmer_s=300, level_tea=7, level_simmer=5)


def fam():
    p = Pantry()
    return [p.profiles["me"], p.profiles["mild"]]


def test_induction_boils_faster_and_refuses_aluminium():
    assert time_to_boil("induction", "steel_saucepan", 500) < time_to_boil("lpg_large", "steel_saucepan", 500) \
        < time_to_boil("lpg_small", "steel_saucepan", 500)
    assert time_to_boil("induction", "aluminium_pan", 500) is None
    assert "error" in simulate_chai(ChaiRecipe(), "induction", "aluminium_pan")


def test_energy_is_conserved_for_tiny_oil_in_heavy_kadhai():
    pot = Pot(VESSELS["iron_kadhai"], SOURCES["induction"], {"oil": 30})
    pot.run_for(10, 60)
    assert pot.t_contents < 150 and pot.t_pot < 150      # no runaway temperatures


def test_long_boiling_pulls_tannins_and_milk_binds_them():
    short, long_ = simulate_chai(ChaiRecipe()), simulate_chai(HABIT)
    assert long_["tannin_mg_l"] > 2.5 * short["tannin_mg_l"]
    milky = simulate_chai(ChaiRecipe(milk_g=300, water_g=100))
    assert milky["tannin_mg_l"] < short["tannin_mg_l"]


def test_over_boiled_chai_has_an_aftertaste_and_the_upgrade_removes_it():
    before = evaluate_chai(HABIT, "lpg_large", "steel_saucepan", fam())
    assert all(p["complaint"] and "aftertaste" in p["complaint"] for p in before["people"])
    res = improve("chai", HABIT.public(), "lpg_large", None, fam(), "upgrade", budget=200)
    after = res["after"]
    assert after["score"] > before["score"] + 5
    assert not any(p["complaint"] and "aftertaste" in p["complaint"] for p in after["people"])
    assert after["sim"]["tannin_mg_l"] < before["sim"]["tannin_mg_l"] / 2
    assert any("Boil the tea" in c for c in res["changes"])
    assert any("flame" in s["text"] for s in res["steps"])          # LPG wording


def test_induction_steps_use_power_levels():
    res = improve("chai", ChaiRecipe().public(), "induction", None, fam(), "upgrade", budget=40)
    assert any("W)" in s["text"] for s in res["steps"])


def test_tadka_burns_more_on_induction_full_power_and_lab_fixes_it():
    full = TadkaRecipe(level=10, fry_level=10)
    lpg, ind = simulate_tadka(full, "lpg_large"), simulate_tadka(full, "induction")
    assert ind["burnt_fraction"] > 2 * lpg["burnt_fraction"] and ind["seconds_to_ready"] < lpg["seconds_to_ready"]
    res = improve("tadka", full.public(), "induction", None, fam(), "upgrade", budget=150)
    assert res["after"]["sim"]["burnt_fraction"] < ind["burnt_fraction"] / 3
    assert res["after"]["sim"]["aroma_fraction"] > 0.7


def test_new_recipe_mode_respects_a_sweet_tooth():
    p = Pantry()
    p.profiles["me"].multipliers["sugar"] = 1.8
    res = improve("chai", {}, "lpg_large", None, [p.profiles["me"]], "new", budget=150)
    assert res["after"]["recipe"]["sugar_g"] > ChaiRecipe().sugar_g
