"""Taste forecast: how salty / sweet / hot / rich the finished dish will be.

There is no off-the-shelf model that predicts a cooked dish's taste from ingredient grams. What sensory
science does support is that perceived saltiness is driven mainly by the salt *fraction* of the food
(e.g. arXiv 2604.20206, "Predicting food taste with bound-driven optimization"), and that perceived
intensity grows as a power of concentration (Stevens' law). So:

    concentration = grams of the ingredient / cooked weight of the dish
    ideal         = the recipe's (or video's) own concentration × the person's profile multiplier
    intensity     = 5 × (concentration / ideal) ** exponent          (5 = "just right", capped at 10)

It's an estimate. The real training signal is the family rating dishes after eating ("too salty",
"just right", "bland"), which nudges each profile: see Pantry.learn_from_rating.
"""
from __future__ import annotations

from dataclasses import dataclass

# taste -> (ingredients that drive it with relative strength, Stevens exponent)
TASTES: dict[str, tuple[dict[str, float], float]] = {
    "salty": ({"salt": 1.0}, 1.3),
    "sweet": ({"sugar": 1.0, "brown_sugar": 0.95, "honey": 0.8}, 1.3),
    "heat": ({"chili": 1.0}, 0.8),
    "earthy": ({"turmeric": 1.0}, 1.0),          # too much turmeric turns bitter / raw
    "rich": ({"ghee": 1.0, "oil": 1.0, "butter": 0.85, "cream": 0.35}, 1.0),
    "soapy": ({"baking_soda": 1.0}, 1.5),        # excess soda tastes soapy / metallic
}
# Default ideal concentrations (fraction of dish weight) when the recipe doesn't say.
DEFAULT_IDEAL = {"salty": 0.009, "sweet": 0.06, "heat": 0.003, "earthy": 0.0015, "rich": 0.04, "soapy": 0.004}

VERDICTS = {
    "salty": ("bland", "needs a little salt", "just right", "a bit salty", "too salty"),
    "sweet": ("not sweet", "a little less sweet", "just right", "a bit sweet", "too sweet"),
    "heat": ("very mild", "mild", "just right", "spicy", "too spicy"),
    "earthy": ("light", "light", "just right", "a bit bitter", "bitter / raw turmeric"),
    "rich": ("dry", "light", "just right", "rich", "very oily"),
    "soapy": ("fine", "fine", "fine", "slightly soapy", "soapy / metallic"),
}


@dataclass
class TasteRow:
    taste: str
    grams: float
    ideal_grams: float
    concentration: float     # fraction of dish weight
    ratio: float             # vs. ideal for this person
    score: float             # 0..10, 5 = just right
    verdict: str
    level: str               # "low" | "ok" | "high"

    def public(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def verdict(taste: str, ratio: float) -> tuple[str, str]:
    v = VERDICTS[taste]
    if ratio < 0.7:
        return v[0], "low"
    if ratio < 0.9:
        return v[1], "low"
    if ratio <= 1.15:
        return v[2], "ok"
    if ratio <= 1.35:
        return v[3], "high"
    return v[4], "high"


def forecast(added: dict[str, float], ideal_grams: dict[str, float], mass_g: float,
             factors: dict[str, float] | None = None) -> list[TasteRow]:
    """added / ideal_grams: grams per ingredient. Only tastes that the recipe sets, or that have
    something added, are reported. `factors` = the profile's multipliers (ideal × factor)."""
    factors = factors or {}
    mass = max(mass_g, 1.0)
    out = []
    for taste, (drivers, exponent) in TASTES.items():
        g = sum(added.get(i, 0.0) * w for i, w in drivers.items())
        ideal = sum(ideal_grams.get(i, 0.0) * w * factors.get(i, 1.0) for i, w in drivers.items())
        if ideal <= 0 and g <= 0:
            continue
        if ideal <= 0:
            if taste in ("soapy", "earthy"):          # these only matter when there's too much
                ideal = DEFAULT_IDEAL[taste] * mass
            else:
                ideal = DEFAULT_IDEAL[taste] * mass * max((factors.get(i, 1.0) for i in drivers), default=1.0)
        ratio = g / ideal if ideal else 0.0
        score = min(10.0, 5.0 * ratio ** exponent) if ratio > 0 else 0.0
        word, level = verdict(taste, ratio)
        if taste in ("soapy", "earthy") and level == "low":
            word, level = "fine", "ok"
        out.append(TasteRow(taste, round(g, 2), round(ideal, 2), g / mass, ratio, round(score, 1), word, level))
    return out
