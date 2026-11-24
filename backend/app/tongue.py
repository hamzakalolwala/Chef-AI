"""A simulated human tongue: taste receptors, how they interact, and whether a person will like the dish.

Pipeline (each step is a standard model from taste science, with approximate literature values):

 1. Chemistry      grams of ingredients -> concentrations in the dish's water phase
                   (NaCl and sucrose in mM, capsaicin in µM, acids, glutamate, fat in g/kg).
 2. Receptors      each taste channel responds with the Beidler / Hill dose-response curve
                       r = C^n / (K^n + C^n)          (0 = nothing, 0.5 = half of max, 1 = saturated)
                   salty   ENaC / Na+ channels      K ≈ 150 mM NaCl  (≈ 0.9 %, a well-salted soup)
                   sweet   T1R2+T1R3                K ≈ 250 mM sucrose (≈ 8.5 %, sweet chai)
                   bitter  T2Rs (25 receptor types) K ≈ 3 g/kg turmeric-equivalent
                   sour    OTOP1 proton channel     K ≈ 8 mM acid
                   umami   T1R1+T1R3                K ≈ 6 mM glutamate
                   heat    TRPV1 (capsaicin; chemesthesis, not a taste)  K ≈ 30 µM capsaicin
                   fat     CD36 / GPR120            K ≈ 60 g fat per kg
 3. Interactions   (mixture effects in the brain / periphery, well documented qualitatively)
                   sweet and salt suppress bitterness · umami boosts saltiness · fat and sugar
                   soften chili heat · sweetness masks sourness.
 4. Perception     intensity 0-10 per channel.
 5. Liking         each person has an ideal intensity per channel (an inverted-U, the classic
                   "bliss point"); overall liking is a weighted geometric mean, so one bad channel
                   (too salty) spoils the dish the way it does at the table.

Tasters differ: receptor sensitivity varies person to person (log-normal), ~25 % are bitter
"super-tasters" and ~25 % "non-tasters" (TAS2R38 / PROP status), and chili tolerance varies widely.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

CHANNELS = ("salty", "sweet", "bitter", "sour", "umami", "heat", "fat", "astringent")

# Hill parameters: half-max concentration K (units per channel) and Hill coefficient n.
RECEPTORS: dict[str, tuple[float, float]] = {
    "salty": (150.0, 1.4),   # mM Na+
    "sweet": (250.0, 1.3),   # mM sucrose-equivalent
    "bitter": (3.0, 1.5),    # g/kg turmeric-equivalent
    "sour": (8.0, 1.2),      # mM titratable acid
    "umami": (6.0, 1.0),     # mM glutamate
    "heat": (30.0, 1.0),     # µM capsaicin
    "fat": (60.0, 1.0),      # g/kg
    "astringent": (900.0, 1.5),  # mg/L free tannin (tea polyphenols): a dry, rough feeling, not a taste bud
}
# How much each channel matters to overall liking, and how forgiving people are (σ in intensity units).
WEIGHT = {"salty": 1.0, "sweet": 0.8, "bitter": 0.7, "sour": 0.5, "umami": 0.3, "heat": 0.8, "fat": 0.4,
          "astringent": 0.7}
SIGMA = {"salty": 1.3, "sweet": 1.6, "bitter": 1.8, "sour": 2.0, "umami": 2.5, "heat": 1.9, "fat": 2.2,
         "astringent": 2.0}
# After swallowing, each sensation fades at its own pace (half-life in seconds). Sweet and salt go fast,
# bitterness, dryness and chili burn linger: that lingering is the "aftertaste".
HALF_LIFE = {"salty": 5, "sweet": 6, "sour": 6, "umami": 12, "fat": 20, "bitter": 30, "astringent": 45, "heat": 90}

MW_NACL, MW_NAHCO3, MW_SUCROSE, MW_CAPSAICIN = 58.44, 84.0, 342.3, 305.4
CHILI_CAPSAICIN_FRACTION = 0.0015   # ≈ 25 000 SHU red chili powder (SHU ≈ 16 × ppm capsaicin)

SWEETENERS = {"sugar": 1.0, "brown_sugar": 0.95, "honey": 0.8, "jaggery": 0.8, "condensed_milk": 0.55,
              "chocolate": 0.45, "chocolate_chips": 0.5}                          # sucrose-equivalent fraction
BITTER = {"turmeric": 1.0, "kasuri_methi": 0.6, "cocoa": 0.5, "baking_soda": 1.5, "hing": 0.4, "chocolate": 0.15}
FATS = {"oil": 1.0, "ghee": 1.0, "butter": 0.82, "cream": 0.35, "milk": 0.035, "egg": 0.10, "chocolate": 0.32,
        "chocolate_chips": 0.30, "almond_flour": 0.5, "paneer": 0.25, "condensed_milk": 0.08, "yogurt": 0.035}
# Titratable acid (mmol per g) for common sour ingredients, matched by name (custom items from videos).
ACIDS = {"lemon": 0.26, "lime": 0.30, "tamarind": 0.6, "vinegar": 0.8, "amchur": 0.5, "curd": 0.09, "buttermilk": 0.09,
         "yogurt": 0.09, "dahi": 0.09, "tomato": 0.035}
# Free glutamate already in the dish (mM), plus glutamate-rich ingredients (mmol per g).
DISH_UMAMI = {"curry": 3.5, "kheema": 3.0, "biryani": 2.5, "soup": 3.0, "dal": 1.5, "khichdi": 1.2,
              "sabzi": 1.5, "eggs": 1.0, "pasta": 1.0, "noodles": 2.0, "poha": 0.8, "rice": 0.3, "chai": 0.2}
GLUTAMATE = {"tomato": 0.017, "cheese": 0.07, "paneer": 0.02, "soy": 0.06, "mushroom": 0.012, "msg": 5.9}
# Water fraction of the cooked dish: tastants dissolve in water, so dry food tastes stronger per gram.
WATER = {"chai": 0.92, "milk": 0.9, "water": 1.0, "soup": 0.9, "dal": 0.8, "khichdi": 0.75, "rice": 0.65,
         "biryani": 0.6, "curry": 0.75, "kheema": 0.65, "sabzi": 0.8, "poha": 0.55, "eggs": 0.75,
         "pasta": 0.65, "noodles": 0.65, "roti": 0.35, "paratha": 0.3, "dosa": 0.5}


def hill(c: float, k: float, n: float) -> float:
    if c <= 0:
        return 0.0
    x = (c / k) ** n
    return x / (1.0 + x)


def water_fraction(dish_id: str | None, grams: dict[str, float]) -> float:
    if dish_id in WATER:
        return WATER[dish_id]
    if grams.get("flour", 0) > 50 or grams.get("besan", 0) > 50:    # dough / baking
        return 0.3
    return 0.75


@dataclass
class Stimulus:
    """Concentrations in the dish's water phase."""
    salty: float = 0.0   # mM Na+
    sweet: float = 0.0   # mM sucrose-eq
    bitter: float = 0.0  # g/kg turmeric-eq (of total dish)
    sour: float = 0.0    # mM acid
    umami: float = 0.0   # mM glutamate
    heat: float = 0.0    # µM capsaicin
    fat: float = 0.0     # g/kg (of total dish)
    astringent: float = 0.0  # mg/L free tannin

    def scaled(self, k: float) -> "Stimulus":
        return Stimulus(**{c: getattr(self, c) * k for c in CHANNELS})


def stimulus(grams: dict[str, float], mass_g: float, dish_id: str | None = None,
             names: dict[str, str] | None = None) -> Stimulus:
    """grams: ingredient id -> grams added. names: id -> display name (to spot 'lemon juice', 'tomato'…)."""
    mass = max(mass_g, 1.0)
    wf = water_fraction(dish_id, grams)
    # Dry foods (cake, cookies, roti) are dissolved by saliva while chewing: without this, a cake's sugar
    # would saturate the sweet receptors and every cake would taste equally (maximally) sweet.
    water_l = mass * (wf + (1.5 if wf < 0.5 else 0.0)) / 1000.0
    s = Stimulus()
    s.salty = (grams.get("salt", 0) / MW_NACL + grams.get("baking_soda", 0) / MW_NAHCO3) * 1000 / water_l
    s.sweet = sum(grams.get(i, 0) * f for i, f in SWEETENERS.items()) / MW_SUCROSE * 1000 / water_l
    s.heat = grams.get("chili", 0) * CHILI_CAPSAICIN_FRACTION / MW_CAPSAICIN * 1e6 / water_l
    s.bitter = sum(grams.get(i, 0) * w for i, w in BITTER.items()) / (mass / 1000)
    s.fat = sum(grams.get(i, 0) * w for i, w in FATS.items()) / (mass / 1000)
    acid_mmol = glu_mmol = 0.0
    for iid, g in grams.items():
        label = f"{iid} {(names or {}).get(iid, '')}".lower()
        acid_mmol += g * next((v for k, v in ACIDS.items() if k in label), 0.0)
        glu_mmol += g * next((v for k, v in GLUTAMATE.items() if k in label), 0.0)
    s.sour = acid_mmol / water_l
    s.umami = DISH_UMAMI.get(dish_id or "", 1.0) + glu_mmol / water_l
    return s


@dataclass
class Taster:
    """One person's tongue: receptor sensitivity (K multipliers; <1 = more sensitive) and bliss points."""
    name: str = "taster"
    sensitivity: dict[str, float] = field(default_factory=dict)
    ideal: dict[str, float] = field(default_factory=dict)     # ideal intensity 0-10 per channel
    bitter_type: str = "medium"                               # super / medium / non (PROP status)
    ideal_after: dict[str, float] = field(default_factory=dict)  # lingering level they're used to

    def k(self, ch: str) -> float:
        return RECEPTORS[ch][0] * self.sensitivity.get(ch, 1.0)


def perceive(t: Taster, s: Stimulus, after_s: float = 0.0) -> dict[str, float]:
    """Receptor responses -> mixture interactions -> perceived intensity 0-10.
    after_s > 0: what's left on the tongue that many seconds after swallowing."""
    r = {ch: hill(getattr(s, ch), t.k(ch), RECEPTORS[ch][1]) * 0.5 ** (after_s / HALF_LIFE[ch]) for ch in CHANNELS}
    out = dict(r)
    out["astringent"] = r["astringent"] * max(0.0, 1 - 0.2 * r["sweet"])            # sugar softens dryness a bit
    out["salty"] = min(1.0, r["salty"] * (1 + 0.2 * r["umami"]))                 # umami enhances salt
    out["bitter"] = r["bitter"] * max(0.0, 1 - 0.35 * r["sweet"] - 0.25 * r["salty"])  # sugar/salt mask bitter
    out["heat"] = r["heat"] * max(0.0, 1 - 0.25 * r["fat"] - 0.15 * r["sweet"])  # fat & sugar calm the burn
    out["sour"] = r["sour"] * max(0.0, 1 - 0.3 * r["sweet"])                     # sweetness masks sourness
    out["sweet"] = r["sweet"] * max(0.0, 1 - 0.15 * r["sour"])
    return {ch: round(10 * v, 2) for ch, v in out.items()}


def liking(t: Taster, intensity: dict[str, float]) -> tuple[float, str | None, dict[str, float]]:
    """Overall liking 0-10, the main complaint ('too salty' / 'needs salt'), and per-channel liking."""
    parts: dict[str, float] = {}
    for ch in CHANNELS:
        ideal = t.ideal.get(ch)
        i = intensity[ch]
        if ch in ("bitter", "sour", "astringent"):
            # Nobody wants these for their own sake: only *more* than expected hurts.
            ceiling = max(1.5, ideal or 0.0)
            parts[ch] = 1.0 if i <= ceiling else math.exp(-((i - ceiling) ** 2) / (2 * SIGMA[ch] ** 2))
            continue
        if ideal is None:
            continue
        parts[ch] = math.exp(-((i - ideal) ** 2) / (2 * SIGMA[ch] ** 2))
    if not parts:
        return 10.0, None, {}
    wsum = sum(WEIGHT[c] for c in parts)
    geo = math.exp(sum(WEIGHT[c] * math.log(max(p, 1e-6)) for c, p in parts.items()) / wsum)
    worst = min(parts, key=parts.get)
    # Penalty analysis: the worst attribute ("too salty") dominates how much people like a dish.
    score = 10 * geo * parts[worst] ** 0.4
    complaint = None
    if parts[worst] < 0.75:
        hi = intensity[worst] > (t.ideal.get(worst) or 1.5)
        words = {"salty": ("too salty", "needs salt"), "sweet": ("too sweet", "not sweet enough"),
                 "bitter": ("bitter", "bitter"), "sour": ("too sour", "needs tang"),
                 "umami": ("too savoury", "flat"), "heat": ("too spicy", "too mild"),
                 "fat": ("too oily", "dry"), "astringent": ("dry, astringent", "dry, astringent")}[worst]
        complaint = words[0] if hi else words[1]
    return round(score, 1), complaint, {c: round(p, 3) for c, p in parts.items()}


def taster_for(name: str, ideal_stim: Stimulus, base: Taster | None = None) -> Taster:
    """A person whose bliss point is what their recipe (× their profile) tastes like on their own tongue."""
    t = Taster(name=name, sensitivity=dict(base.sensitivity) if base else {},
               bitter_type=base.bitter_type if base else "medium")
    ideal = perceive(t, ideal_stim)
    t.ideal = {ch: ideal[ch] for ch in ("salty", "sweet", "heat", "fat", "umami") if ideal[ch] > 0.05}
    for ch in ("bitter", "sour", "astringent"):   # the turmeric / lemon / tea the recipe calls for is expected
        if ideal[ch] > 0.05:
            t.ideal[ch] = ideal[ch]
    after = perceive(t, ideal_stim, 30.0)
    t.ideal_after = {ch: after[ch] for ch in ("bitter", "astringent")}
    return t


def random_taster(rng: np.random.Generator, ideal_stim: Stimulus, name: str = "panel") -> Taster:
    """A member of the public: varied receptors, PROP bitter status, varied chili tolerance and preferences."""
    sens = {ch: float(np.exp(rng.normal(0, 0.25))) for ch in CHANNELS}
    u = rng.random()
    bitter_type = "super" if u < 0.25 else "non" if u > 0.75 else "medium"
    sens["bitter"] *= {"super": 0.45, "medium": 1.0, "non": 2.2}[bitter_type]
    sens["heat"] *= float(np.exp(rng.normal(0.3, 0.5)))           # chili-habituated palates tolerate more
    base = Taster(name, sensitivity=sens, bitter_type=bitter_type)
    pref = ideal_stim.scaled(1.0)
    pref.salty *= float(np.exp(rng.normal(0, 0.18)))             # personal salt / sugar / chili preference
    pref.sweet *= float(np.exp(rng.normal(0, 0.25)))
    pref.heat *= float(np.exp(rng.normal(0, 0.35)))
    return taster_for(name, pref, base)


def panel_verdict(stim: Stimulus, ideal_stim: Stimulus, n: int = 40, seed: int = 0) -> dict:
    """How a panel of n varied people would rate this dish."""
    rng = np.random.default_rng(seed)
    scores, complaints = [], {}
    for _ in range(n):
        t = random_taster(rng, ideal_stim)
        sc, comp, _ = liking(t, perceive(t, stim))
        scores.append(sc)
        if comp:
            complaints[comp] = complaints.get(comp, 0) + 1
    return {"mean": round(float(np.mean(scores)), 2), "liked_%": round(100 * float(np.mean(np.array(scores) >= 7)), 1),
            "complaints": dict(sorted(complaints.items(), key=lambda kv: -kv[1]))}


def aftertaste(t: Taster, s: Stimulus, after_s: float = 30.0) -> tuple[float, str | None, dict[str, float]]:
    """How pleasant the finish is: lingering bitterness or dryness spoils it (0-1, complaint, what lingers).
    Sweetness masks bitterness while sipping but fades first, so the bitterness shows up afterwards."""
    left = perceive(t, s, after_s)
    pen_b = math.exp(-max(0.0, left["bitter"] - max(1.0, t.ideal_after.get("bitter", 0) + 0.6)) ** 2 / (2 * 1.2 ** 2))
    pen_a = math.exp(-max(0.0, left["astringent"] - max(1.2, t.ideal_after.get("astringent", 0) + 0.6)) ** 2
                     / (2 * 1.4 ** 2))
    f = pen_b * pen_a
    complaint = None
    if f < 0.8:
        complaint = "bitter aftertaste" if pen_b <= pen_a else "dry, astringent aftertaste"
    return round(f, 3), complaint, left


def overall(t: Taster, s: Stimulus) -> dict:
    """Sip + finish: the score people actually give after a few sips."""
    sip = perceive(t, s)
    score, complaint, _ = liking(t, sip)
    f, after_complaint, left = aftertaste(t, s)
    total = round(score * f ** 0.35, 1)
    return {"score": total, "sip_score": score, "finish": f, "complaint": after_complaint if f < 0.8 and
            (complaint is None or f < 0.6) else complaint, "sip": sip, "after": left}
