"""Recipe balance: why "just add more flour" ruins a cake, and how to change one thing without breaking the rest.

Every ingredient does jobs (classic baking-science framing):
    STRUCTURE   (tougheners)  flour, eggs (whites), cocoa, milk solids      -> holds the shape
    TENDERNESS  (tenderisers) sugar, fat, leavening, egg yolk              -> soft, short crumb
    MOISTURE    (moisteners)  water in milk / eggs / curd, liquid sugar     -> moist, not dry
    DRYING      (driers)      flour, starch, cocoa, milk powder             -> soaks up liquid

A balanced formula keeps STRUCTURE : TENDERNESS and MOISTURE : DRYING in a range that depends on the
product (cake, cookie, brownie…). The ranges come from *your reference recipes* (your sister's sheet)
when there are enough of them, otherwise from rough general defaults below. Savoury dishes get the same
treatment with salt, fat, acid and spice load per kilo.

Compositions are approximate per-100 g values from standard food tables.
"""
from __future__ import annotations

from dataclasses import dataclass

# fraction by weight: water, fat, sugar, protein, starch, acid (as lactic/citric), leavening (active g/g)
COMPOSITION: dict[str, dict[str, float]] = {
    "flour": {"water": .12, "protein": .10, "starch": .75, "fat": .01},
    "semolina": {"water": .12, "protein": .12, "starch": .72, "fat": .01},
    "besan": {"water": .10, "protein": .22, "starch": .55, "fat": .06},
    "cornflour": {"water": .10, "starch": .88},
    "almond_flour": {"water": .04, "protein": .21, "fat": .50, "starch": .10},
    "cocoa": {"water": .03, "protein": .20, "fat": .12, "starch": .45, "acid": .01},
    "milk_powder": {"water": .03, "protein": .26, "fat": .26, "sugar": .38},
    "egg": {"water": .75, "protein": .13, "fat": .10},
    "butter": {"water": .16, "fat": .81},
    "ghee": {"fat": .995},
    "oil": {"fat": 1.0},
    "sugar": {"sugar": 1.0},
    "brown_sugar": {"sugar": .95, "water": .02, "acid": .003},
    "honey": {"sugar": .82, "water": .17, "acid": .005},
    "jaggery": {"sugar": .85, "water": .05, "acid": .002},
    "condensed_milk": {"sugar": .55, "water": .27, "fat": .08, "protein": .08},
    "chocolate": {"sugar": .45, "fat": .32, "protein": .06, "starch": .10},
    "chocolate_chips": {"sugar": .50, "fat": .30, "protein": .05, "starch": .10},
    "milk": {"water": .87, "fat": .035, "protein": .033, "sugar": .048},
    "cream": {"water": .58, "fat": .35, "protein": .02, "sugar": .03},
    "yogurt": {"water": .85, "fat": .035, "protein": .04, "sugar": .04, "acid": .009},
    "buttermilk": {"water": .90, "fat": .01, "protein": .03, "sugar": .04, "acid": .008},
    "lemon_juice": {"water": .92, "acid": .05, "sugar": .02},
    "water": {"water": 1.0},
    "baking_powder": {"leaven": 1.0, "starch": .3},
    "baking_soda": {"leaven": 3.0},           # ~3× stronger than baking powder, needs an acid
    "vanilla": {"water": .6},
    "salt": {},
    "paneer": {"water": .55, "fat": .25, "protein": .18},
    "capsicum": {"water": .93, "sugar": .025}, "onion": {"water": .89, "sugar": .045},
    "tomato": {"water": .94, "sugar": .026, "acid": .004}, "potato": {"water": .79, "starch": .17},
    "carrot": {"water": .88, "sugar": .047},
}
# Weight of one piece when a recipe counts instead of weighing ("2 eggs", "1 onion")
PIECE_G = {"egg": 50, "onion": 150, "tomato": 110, "capsicum": 150, "potato": 170, "carrot": 80,
           "lemon_juice": 30, "banana": 120}
FLAVOURINGS = {"vanilla", "salt", "cardamom", "cumin", "turmeric", "chili", "garam_masala", "coriander_powder",
               "hing", "kasuri_methi", "mustard_seeds", "coriander_seeds", "coriander_leaves", "ginger_garlic_paste"}

BAKING_KINDS = ("cake", "cupcake", "muffin", "cookie", "brownie", "bread", "pancake")
# Rough general ranges (min, max). Your reference recipes override these per category.
DEFAULT_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "cake":    {"structure_tender": (0.45, 0.95), "moist_dry": (0.85, 1.6), "leaven_pct": (1.5, 5.0),
                "sugar_pct": (60, 140), "fat_pct": (25, 115), "egg_pct": (35, 110), "salt_pct": (0.3, 2.0)},
    "muffin":  {"structure_tender": (0.6, 1.3), "moist_dry": (0.9, 1.6), "leaven_pct": (2.0, 6.0),
                "sugar_pct": (40, 100), "fat_pct": (20, 60), "egg_pct": (20, 70), "salt_pct": (0.3, 2.0)},
    "cookie":  {"structure_tender": (0.45, 1.25), "moist_dry": (0.15, 0.6), "leaven_pct": (0.3, 3.0),
                "sugar_pct": (50, 130), "fat_pct": (40, 100), "egg_pct": (0, 45), "salt_pct": (0.5, 2.5)},
    "brownie": {"structure_tender": (0.2, 0.75), "moist_dry": (0.4, 1.2), "leaven_pct": (0, 2.0),
                "sugar_pct": (100, 260), "fat_pct": (60, 180), "egg_pct": (60, 180), "salt_pct": (0.3, 2.5)},
    "bread":   {"structure_tender": (2.0, 25.0), "moist_dry": (0.55, 0.85), "leaven_pct": (0, 3.0),
                "sugar_pct": (0, 15), "fat_pct": (0, 15), "egg_pct": (0, 30), "salt_pct": (1.5, 2.5)},
    "dessert": {"sugar_total_pct": (8, 30), "fat_total_pct": (2, 25)},
    "savoury": {"salt_total_pct": (0.7, 1.4), "fat_total_pct": (2, 12), "spice_per_kg": (5, 40)},
}
ADVICE = {
    "moist_dry": ("too dry / dense ('cakey'): needs more milk, curd or egg, or less flour",
                  "too wet / gummy: needs less liquid or a little more flour"),
    "structure_tender": ("crumbly / may collapse: needs more flour or egg for structure",
                         "tough / chewy: needs more sugar, fat or leavening, or fewer eggs"),
    "leaven_pct": ("won't rise much: needs more baking powder/soda", "may rise then sink, coarse or soapy: too much leavening"),
    "sugar_pct": ("not very sweet, drier and paler", "very sweet; spreads more, browns fast"),
    "fat_pct": ("lean and dry", "greasy / heavy"),
    "egg_pct": ("weak structure", "eggy, rubbery"),
    "salt_pct": ("flat taste", "salty"),
    "salt_total_pct": ("under-salted", "too salty"),
    "fat_total_pct": ("dry / lean", "oily"),
    "spice_per_kg": ("bland", "over-spiced"),
    "sugar_total_pct": ("not sweet enough", "very sweet"),
}


def grams_of(items: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for it in items:
        if it.get("ingredient") and it.get("grams"):
            out[it["ingredient"]] = out.get(it["ingredient"], 0.0) + float(it["grams"])
    return out


def totals(g: dict[str, float]) -> dict[str, float]:
    t = {k: 0.0 for k in ("water", "fat", "sugar", "protein", "starch", "acid", "leaven")}
    for iid, grams in g.items():
        for k, frac in COMPOSITION.get(iid, {"water": 0.5}).items():
            t[k] += grams * frac
    t["mass"] = sum(g.values())
    return t


def flour_weight(g: dict[str, float]) -> float:
    return sum(g.get(i, 0) * w for i, w in
               (("flour", 1), ("semolina", 1), ("besan", 1), ("cornflour", 1), ("almond_flour", .6), ("cocoa", 1)))


def ratios(g: dict[str, float], category: str) -> dict[str, float]:
    """Balance numbers for a recipe (grams per ingredient id)."""
    t = totals(g)
    if category in BAKING_KINDS:
        fl = max(flour_weight(g), 1e-6)
        egg = g.get("egg", 0)
        structure = (g.get("flour", 0) + g.get("semolina", 0) + g.get("besan", 0) + 0.6 * g.get("cornflour", 0)
                     + g.get("cocoa", 0) + 0.3 * g.get("almond_flour", 0) + 0.45 * egg + 0.5 * g.get("milk_powder", 0))
        tender = t["sugar"] + t["fat"] + 25 * t["leaven"] + 0.15 * egg
        moist = t["water"] + 0.4 * t["sugar"] * (g.get("honey", 0) + g.get("condensed_milk", 0) > 0)
        dry = fl + g.get("milk_powder", 0)
        return {
            "structure_tender": structure / max(tender, 1e-6),
            "moist_dry": moist / max(dry, 1e-6),
            "leaven_pct": 100 * t["leaven"] / fl,
            "sugar_pct": 100 * t["sugar"] / fl,
            "fat_pct": 100 * t["fat"] / fl,
            "egg_pct": 100 * egg / fl,
            "salt_pct": 100 * g.get("salt", 0) / fl,
            "soda_acid": g.get("baking_soda", 0) / max(t["acid"] * 1.6 + 1e-6, 1e-6),   # >1.3: soapy, unreacted soda
        }
    mass = max(t["mass"], 1e-6)
    spice = sum(g.get(i, 0) for i in FLAVOURINGS if i not in ("salt", "vanilla"))
    if category == "dessert":
        return {"sugar_total_pct": 100 * t["sugar"] / mass, "fat_total_pct": 100 * t["fat"] / mass}
    return {"salt_total_pct": 100 * g.get("salt", 0) / mass, "fat_total_pct": 100 * t["fat"] / mass,
            "spice_per_kg": 1000 * spice / mass}


@dataclass
class Issue:
    key: str
    value: float
    lo: float
    hi: float
    message: str
    severity: str     # "warn" | "bad"

    def public(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def check(g: dict[str, float], category: str, ranges: dict[str, tuple[float, float]] | None = None) -> list[Issue]:
    ranges = ranges or DEFAULT_RANGES.get(category, DEFAULT_RANGES["savoury"])
    r = ratios(g, category)
    out = []
    for k, (lo, hi) in ranges.items():
        if k not in r:
            continue
        v = r[k]
        if v < lo or v > hi:
            span = max(hi - lo, 1e-6)
            off = (lo - v) / span if v < lo else (v - hi) / span
            low_msg, high_msg = ADVICE.get(k, ("too low", "too high"))
            out.append(Issue(k, v, lo, hi, low_msg if v < lo else high_msg, "bad" if off > 0.35 else "warn"))
    if category in BAKING_KINDS and g.get("baking_soda", 0) > 0 and r.get("soda_acid", 0) > 1.3:
        out.append(Issue("soda_acid", r["soda_acid"], 0, 1.3, "baking soda without enough acid: soapy/metallic "
                         "taste and brown colour; add curd/buttermilk/lemon or use baking powder", "warn"))
    return out


def learn_ranges(recipes: list[dict[str, float]], category: str, min_n: int = 2) -> dict[str, tuple[float, float]]:
    """Ranges from reference recipes: their spread, widened a little; general defaults where too few."""
    base = dict(DEFAULT_RANGES.get(category, DEFAULT_RANGES["savoury"]))
    if len(recipes) < min_n:
        if len(recipes) == 1:      # one trusted recipe: centre the general range on it
            r = ratios(recipes[0], category)
            for k, (lo, hi) in base.items():
                if k in r:
                    half = (hi - lo) / 4
                    base[k] = (max(0.0, r[k] - half), r[k] + half)
        return base
    vals: dict[str, list[float]] = {}
    for g in recipes:
        for k, v in ratios(g, category).items():
            vals.setdefault(k, []).append(v)
    for k, vs in vals.items():
        if k not in base:
            continue
        lo, hi = min(vs), max(vs)
        pad = max((hi - lo) * 0.15, abs(hi + lo) / 2 * 0.12)
        base[k] = (max(0.0, lo - pad), hi + pad)
    return base
