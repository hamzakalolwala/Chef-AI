"""Adapt any recipe (Pinterest text, a YouTube video, a pasted list) to *your* sweet spot without breaking it.

Your sister's point: in baking you can't change one thing alone. Cut the sugar and the cake also gets
drier and tougher (sugar tenderises and holds moisture); add a cup of flour with the same two eggs and
it turns dry and cakey. So the adapter changes *groups* of ingredients together:

    minimise   taste distance to the sweet spot (simulated tongue vs. your reference recipes)
             + balance penalty (structure / tenderness / moisture ratios outside the reference range)
             + change penalty (keep it recognisably the original recipe)

The main dry ingredient (flour / dal / rice: the "anchor") stays fixed so the batch size doesn't change.
"""
from __future__ import annotations

import math

from .balance import BAKING_KINDS, DEFAULT_RANGES, FLAVOURINGS, PIECE_G, check, grams_of, ratios
from .pantry import Pantry
from .reference import taste_of

ADJUSTABLE = {"sugar", "brown_sugar", "honey", "jaggery", "condensed_milk", "butter", "ghee", "oil", "cream", "milk",
              "water", "yogurt", "buttermilk", "egg", "baking_powder", "baking_soda", "salt", "cocoa", "chocolate",
              "chocolate_chips", "lemon_juice", "vanilla", "milk_powder", "chili", "turmeric", "garam_masala",
              "coriander_powder", "cumin", "cardamom"}
TASTE_W = {"sweet": 1.6, "bitter": 1.0, "sour": 0.8, "salty": 1.2, "fat": 0.5, "heat": 0.8}
ROLE = {"sugar": "sweetness", "brown_sugar": "sweetness", "honey": "sweetness", "jaggery": "sweetness",
        "condensed_milk": "sweetness", "butter": "tenderness / richness", "ghee": "richness", "oil": "tenderness",
        "cream": "moisture / richness", "milk": "moisture", "water": "moisture", "yogurt": "moisture / tang",
        "buttermilk": "moisture / tang", "egg": "structure + moisture", "baking_powder": "rise",
        "baking_soda": "rise", "salt": "seasoning", "cocoa": "chocolate flavour (bitter)", "lemon_juice": "tang"}


def _anchor(g: dict[str, float], category: str) -> str:
    dry = [i for i in ("flour", "semolina", "besan", "almond_flour", "rice", "toor_dal", "moong_dal") if g.get(i)]
    if dry:
        return max(dry, key=lambda i: g[i])
    return max(g, key=g.get)


def score_parts(g: dict[str, float], pantry: Pantry, category: str, target: dict | None,
                ranges: dict) -> tuple[float, float, dict]:
    taste = taste_of(g, pantry, category)
    t_cost = 0.0
    if target:
        for ch, w in TASTE_W.items():
            tc = target.get(ch)
            if not tc or (tc["mid"] < 0.15 and taste[ch] < 0.6):
                continue
            half = max((tc["hi"] - tc["lo"]) / 2, 0.35)
            t_cost += w * ((taste[ch] - tc["mid"]) / (half + 0.5)) ** 2
    b_cost = 0.0
    r = ratios(g, category)
    for k, (lo, hi) in ranges.items():
        if k not in r:
            continue
        span = max(hi - lo, 1e-6)
        v = r[k]
        out = (lo - v) / span if v < lo else (v - hi) / span if v > hi else 0.0
        centre = (v - (lo + hi) / 2) / span
        b_cost += 14 * out * out + 0.15 * centre * centre
    return t_cost, b_cost, taste


def adapt(items: list[dict], category: str, pantry: Pantry, target: dict | None = None,
          ranges: dict | None = None) -> dict:
    ranges = ranges or DEFAULT_RANGES.get(category, DEFAULT_RANGES["savoury"])
    g0 = grams_of(items)
    if not g0:
        return {"error": "No ingredients with amounts to work with"}
    anchor = _anchor(g0, category)
    keys = [k for k in g0 if k in ADJUSTABLE and k != anchor and g0[k] > 0]
    logm = {k: 0.0 for k in keys}

    def apply(lm: dict[str, float]) -> dict[str, float]:
        return {k: (v * math.exp(lm[k]) if k in lm else v) for k, v in g0.items()}

    def cost(lm: dict[str, float]) -> float:
        t, b, _ = score_parts(apply(lm), pantry, category, target, ranges)
        change = sum(0.25 * x * x for x in lm.values())
        return t + b + change

    best = cost(logm)
    for step in (0.4, 0.2, 0.1, 0.05):
        improved = True
        rounds = 0
        while improved and rounds < 12:
            improved = False
            rounds += 1
            for k in keys:
                for d in (step, -step):
                    trial = dict(logm)
                    trial[k] = max(-1.6, min(1.0, trial[k] + d))
                    c = cost(trial)
                    if c < best - 1e-4:
                        best, logm, improved = c, trial, True
    g1 = apply(logm)
    if "egg" in g1:            # whole or half eggs only
        g1["egg"] = max(25.0, round(g1["egg"] / 25) * 25)
    for k in list(g1):
        if k not in ("egg",) and k in logm:
            g1[k] = round(g1[k], 1 if g1[k] < 10 else 0)

    t0, b0, taste0 = score_parts(g0, pantry, category, target, ranges)
    t1, b1, taste1 = score_parts(g1, pantry, category, target, ranges)
    changes = []
    for k in keys:
        a, b = g0[k], g1[k]
        if abs(b - a) / max(a, 1e-6) < 0.06:
            continue
        name = pantry.ingredients[k].name if k in pantry.ingredients else k
        pct = round(100 * (b - a) / a)
        why = ROLE.get(k, "flavour")
        changes.append({"ingredient": k, "name": name, "from_g": round(a, 1), "to_g": round(b, 1), "pct": pct,
                        "why": why, "text": f"{name}: {_amount(k, a, pantry)} → {_amount(k, b, pantry)} "
                        f"({'+' if pct > 0 else ''}{pct}%) — {why}"})
    sweet_down = any(c["ingredient"] in ("sugar", "brown_sugar", "condensed_milk", "jaggery") and c["pct"] < 0 for c in changes)
    comp = [c["name"].lower() for c in changes if c["pct"] > 0 and c["ingredient"] in
            ("milk", "water", "yogurt", "buttermilk", "butter", "oil", "cream", "egg")]
    notes = []
    if sweet_down and comp and category in BAKING_KINDS:
        notes.append(f"Less sugar also means less tenderness and moisture, so {', '.join(comp)} went up a little "
                     "to keep the crumb soft.")
    out_items = []
    for it in items:
        k = it.get("ingredient")
        new_g = g1.get(k) if k else None
        out_items.append({**it, "new_grams": new_g if k in logm or k == "egg" else it.get("grams"),
                          "new_amount": _amount(k, new_g, pantry) if k and new_g else None})
    return {
        "category": category, "anchor": anchor, "items": out_items, "changes": changes, "notes": notes,
        "taste_before": taste0, "taste_after": taste1, "target": target,
        "balance_before": [i.public() for i in check(g0, category, ranges)],
        "balance_after": [i.public() for i in check(g1, category, ranges)],
        "ratios_before": {k: round(v, 3) for k, v in ratios(g0, category).items()},
        "ratios_after": {k: round(v, 3) for k, v in ratios(g1, category).items()},
        "ranges": {k: list(v) for k, v in ranges.items()},
        "fit_before": round(t0 + b0, 3), "fit_after": round(t1 + b1, 3),
    }


def _amount(iid: str | None, grams: float | None, pantry: Pantry) -> str:
    """Grams plus a kitchen measure (cups / tbsp / tsp / eggs) for people who don't weigh."""
    if grams is None:
        return "—"
    if iid in PIECE_G:
        n = grams / PIECE_G[iid]
        return f"{n:g} {'egg' if iid == 'egg' else 'pc'}{'s' if n != 1 and iid == 'egg' else ''} (~{grams:.0f} g)"
    dens = pantry.ingredients[iid].density if iid in pantry.ingredients else 0.6
    ml = grams / dens
    if iid in FLAVOURINGS or ml < 15:
        tsp = ml / 5
        measure = f"{tsp:.1f} tsp" if tsp < 3 else f"{ml / 15:.1f} tbsp"
    elif ml < 60:
        measure = f"{ml / 15:.1f} tbsp"
    else:
        measure = f"{ml / 240:.2f} cup"
    return f"{grams:.0f} g ({measure})" if grams >= 10 else f"{grams:.1f} g ({measure})"
