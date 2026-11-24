"""Recipe Lab: upgrade an old recipe ("no aftertaste in my chai") or generate a new one, for a given heat
source (LPG / induction), pot and set of people.

Each candidate recipe is cooked in simulation (heat.py -> cookchem.py), tasted by every chosen person's
simulated tongue including the finish 30 s after swallowing (tongue.py), and scored. A simple
stochastic local search then changes amounts, timings and heat settings. "Upgrade" mode prefers few
changes so the recipe stays recognisably yours; "new" starts from a good reference and is free.
"""
from __future__ import annotations

import copy
import math
from dataclasses import fields

import numpy as np

from .cookchem import (CHAI_BOUNDS, TADKA_BOUNDS, ChaiRecipe, TadkaRecipe, mmss, setting, simulate_chai,
                       simulate_tadka)
from .heat import SOURCES, VESSELS
from .tongue import Stimulus, overall, stimulus, taster_for

STEP = {"tea_g": 0.5, "sugar_g": 1, "ginger_g": 0.5, "cardamom_g": 0.25, "tea_boil_s": 10, "milk_simmer_s": 10,
        "level_tea": 1, "level_simmer": 1, "cardamom_last_s": 10, "milk_g": 10, "water_g": 10,
        "level": 1, "add_at_c": 5, "fry_s": 5, "fry_level": 1}
LABEL = {"tea_g": "Tea leaves", "sugar_g": "Sugar", "ginger_g": "Ginger", "cardamom_g": "Cardamom",
         "tea_boil_s": "Boil the tea", "milk_simmer_s": "Simmer after milk", "level_tea": "Heat while tea boils",
         "level_simmer": "Heat after milk", "cardamom_last_s": "Add cardamom", "milk_g": "Milk", "water_g": "Water",
         "level": "Heat the oil on", "add_at_c": "Add spices at", "fry_s": "Let the spices crackle",
         "fry_level": "Heat while spices fry"}


def _round(k: str, v: float) -> float:
    st = STEP[k]
    return round(round(v / st) * st, 3)


# ---------------------------------------------------------------------------------------------- chai
def chai_stimulus(o: dict) -> Stimulus:
    water_l = max(o["volume_ml"], 1) / 1000
    return Stimulus(
        sweet=o["sugar_g"] / 342.3 * 1000 / water_l,
        bitter=o["tannin_mg_l"] / 350 + o["caffeine_mg_l"] / 500,   # catechins + caffeine, turmeric-eq g/kg
        astringent=o["tannin_mg_l"],
        heat=o["pungency"] * 0.05,                                     # ginger: far milder than capsaicin
        fat=o["milk_fat_g"] / (o["mass_g"] / 1000),
        umami=0.2,
    )


_REF: dict = {}


def chai_reference() -> tuple[dict, Stimulus]:
    """A well-made chai (the default ChaiRecipe on a large LPG burner): everyone's starting bliss point."""
    if not _REF:
        o = simulate_chai(ChaiRecipe(), "lpg_large", "steel_saucepan")
        _REF["o"], _REF["s"] = o, chai_stimulus(o)
    return _REF["o"], _REF["s"]


def _flavour(o: dict, ref: dict) -> tuple[float, str | None]:
    """Smell + strength (not the tongue): too weak / too strong tea, cardamom aroma."""
    s = math.log(max(o["strength"], 0.1) / ref["strength"])
    f_s = math.exp(-s * s / (2 * 0.6 ** 2))
    f_a = 1.0
    if ref["aroma"] > 0:
        a = math.log((o["aroma"] + 0.1) / (ref["aroma"] + 0.1))
        f_a = math.exp(-a * a / (2 * 0.8 ** 2))
    why = None
    if f_s < 0.75:
        why = "too strong" if s > 0 else "too weak"
    elif f_a < 0.7:
        why = "not enough cardamom" if o["aroma"] < ref["aroma"] else "too much cardamom"
    return f_s * f_a, why


def _people(profiles) -> list:
    return list(profiles) or [None]


def evaluate_chai(r: ChaiRecipe, source: str, vessel: str, profiles) -> dict:
    o = simulate_chai(r, source, vessel)
    if "error" in o:
        return o
    ref_o, ref_s = chai_reference()
    stim = chai_stimulus(o)
    per = []
    for p in _people(profiles):
        ideal = copy.copy(ref_s)
        if p is not None:
            ideal.sweet *= p.factor("sugar")
            ideal.heat *= p.factor("chili")
        t = taster_for(p.name if p else "you", ideal)
        ov = overall(t, stim)
        flav, why = _flavour(o, ref_o)
        score = round(ov["score"] * flav ** 0.35, 1)
        per.append({"id": p.id if p else "you", "name": p.name if p else "You", "emoji": p.emoji if p else "🙂",
                    "score": score, "finish": ov["finish"], "complaint": ov["complaint"] or why,
                    "sip": ov["sip"], "after": ov["after"]})
    return {"dish": "chai", "score": round(float(np.mean([x["score"] for x in per])), 2), "people": per,
            "sim": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in o.items() if k not in ("temps",)},
            "temps": o["temps"]}


# ---------------------------------------------------------------------------------------------- tadka
DAL = {"salt": 8, "turmeric": 1.5, "chili": 2, "ghee": 12}


def evaluate_tadka(r: TadkaRecipe, source: str, vessel: str, profiles) -> dict:
    o = simulate_tadka(r, source, vessel)
    if "error" in o:
        return o
    base = stimulus({**DAL, "ghee": DAL["ghee"] + r.oil_g}, 1000, "dal")
    cooked = copy.copy(base)
    cooked.bitter += o["bitter_g"]            # burnt jeera, in a 1 kg pot of dal
    aroma_f = min(1.0, o["aroma_fraction"] / 0.85) ** 0.7
    pop_f = 1.0 if o["mustard_popped"] else 0.75
    per = []
    for p in _people(profiles):
        ideal = stimulus({**DAL, "ghee": DAL["ghee"] + r.oil_g,
                          **({"salt": 8 * p.factor("salt"), "chili": 2 * p.factor("chili")} if p else {})}, 1000, "dal")
        t = taster_for(p.name if p else "you", ideal)
        ov = overall(t, cooked)
        score = round(ov["score"] * aroma_f * pop_f, 1)
        why = ov["complaint"] or (None if aroma_f > 0.85 else "spices didn't bloom") or \
            (None if pop_f == 1 else "mustard didn't pop")
        per.append({"id": p.id if p else "you", "name": p.name if p else "You", "emoji": p.emoji if p else "🙂",
                    "score": score, "finish": ov["finish"], "complaint": why, "sip": ov["sip"], "after": ov["after"]})
    return {"dish": "tadka", "score": round(float(np.mean([x["score"] for x in per])), 2), "people": per,
            "sim": {k: v for k, v in o.items() if k != "temps"}, "temps": o["temps"]}


DISHES = {
    "chai": (ChaiRecipe, CHAI_BOUNDS, evaluate_chai, "steel_saucepan"),
    "tadka": (TadkaRecipe, TADKA_BOUNDS, evaluate_tadka, "iron_kadhai"),
}


def describe_changes(dish: str, before, after, source: str) -> list[str]:
    out = []
    for f in fields(before):
        a, b = getattr(before, f.name), getattr(after, f.name)
        if a == b or f.name not in LABEL:
            continue
        lab = LABEL[f.name]
        if f.name.endswith("_s") and f.name != "cardamom_last_s":
            out.append(f"{lab} for {mmss(b)} instead of {mmss(a)}")
        elif f.name == "cardamom_last_s":
            out.append(f"{lab} {mmss(b)} before the end (was {mmss(a)})")
        elif f.name.startswith("level") or f.name == "fry_level":
            out.append(f"{lab} {setting(source, b)} instead of {setting(source, a)}")
        elif f.name == "add_at_c":
            out.append(f"{lab} ~{b:g} °C instead of ~{a:g} °C")
        else:
            unit = " ml" if f.name in ("milk_g", "water_g") else " g"
            out.append(f"{lab}: {b:g}{unit} instead of {a:g}{unit}")
    return out


def improve(dish: str, recipe: dict, source: str, vessel: str | None, profiles, mode: str = "upgrade",
            budget: int = 260, seed: int = 0) -> dict:
    cls, bounds, evaluate, default_vessel = DISHES[dish]
    vessel = vessel or default_vessel
    base = cls(**recipe) if mode == "upgrade" else cls()
    before = evaluate(base, source, vessel, profiles)
    if "error" in before:
        return before
    rng = np.random.default_rng(seed)
    keys = list(bounds)
    base_min = before["sim"].get("minutes", 0)

    def objective(r, ev) -> float:
        changed = sum(1 for k in keys if abs(getattr(r, k) - getattr(base, k)) > 1e-9)
        minutes = ev["sim"].get("minutes", 0) if dish == "chai" else ev["sim"].get("seconds_to_ready", 0) / 60
        longer = max(0.0, minutes - base_min - 2) if dish == "chai" else 0.0
        return ev["score"] - (0.12 * changed if mode == "upgrade" else 0) - 0.15 * longer - 0.04 * minutes

    best, best_ev = base, before
    best_obj = objective(base, before)
    cur, cur_obj = best, best_obj
    for i in range(budget):
        cand = copy.deepcopy(cur)
        for k in rng.choice(keys, size=int(rng.integers(1, 3)), replace=False):
            lo, hi = bounds[k]
            span = (hi - lo) * (0.35 * (1 - i / budget) + 0.05)
            setattr(cand, k, float(np.clip(_round(k, getattr(cand, k) + rng.normal(0, span)), lo, hi)))
        ev = evaluate(cand, source, vessel, profiles)
        if "error" in ev:
            continue
        obj = objective(cand, ev)
        if obj > cur_obj or rng.random() < 0.03:      # occasional sideways step to escape plateaus
            cur, cur_obj = cand, obj
            if obj > best_obj:
                best, best_ev, best_obj = cand, ev, obj
    # Drop changes that don't pull their weight (keeps an upgrade as small as possible).
    if mode == "upgrade":
        for k in keys:
            if getattr(best, k) != getattr(base, k):
                trial = copy.deepcopy(best)
                setattr(trial, k, getattr(base, k))
                ev = evaluate(trial, source, vessel, profiles)
                if "error" not in ev and ev["score"] >= best_ev["score"] - 0.1:
                    best, best_ev = trial, ev
    sim = (simulate_chai if dish == "chai" else simulate_tadka)(best, source, vessel)
    others = {}
    for sid in SOURCES:
        if sid != source:
            ev = evaluate(best, sid, vessel, profiles)
            others[sid] = None if "error" in ev else {"score": ev["score"], "minutes": ev["sim"].get("minutes"),
                                                      "complaints": [p["complaint"] for p in ev["people"] if p["complaint"]]}
    return {
        "dish": dish, "mode": mode, "source": source, "vessel": vessel,
        "before": {"recipe": base.public(), **before},
        "after": {"recipe": best.public(), **best_ev},
        "changes": describe_changes(dish, base, best, source),
        "steps": sim["steps"],
        "same_recipe_on_other_sources": others,
    }


def options() -> dict:
    return {
        "sources": [{"id": s.id, "name": s.name, "kind": s.kind} for s in SOURCES.values()],
        "vessels": [{"id": v.id, "name": v.name, "induction_ok": v.induction_ok} for v in VESSELS.values()],
        "dishes": {"chai": ChaiRecipe().public(), "tadka": TadkaRecipe().public()},
        "bounds": {"chai": CHAI_BOUNDS, "tadka": TADKA_BOUNDS},
    }
