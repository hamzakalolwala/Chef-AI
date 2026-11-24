"""Cooking chemistry on top of the heat model: what comes out of tea leaves and spices, and when.

First-order extraction with Arrhenius temperature dependence:
    amount(t) = max × (1 - e^(-k(T)·t)),   k(T) = k100 · exp(-Ea/R · (1/T - 1/373 K))

CHAI (CTC black tea, approximate literature-style values)
    strength (theaflavins, colour/briskness)  fast   k100 ≈ 0.6 /min   (mostly out in ~4 min)
    caffeine                                   fast   k100 ≈ 0.8 /min
    tannins / catechins (astringent, bitter)   slow   k100 ≈ 0.12 /min, keeps rising with long boiling
    milk proteins (casein) bind part of the tannins, so less "dry" feeling on the tongue
    ginger: gingerol extracts (k ≈ 0.35 /min); long boiling turns some into hotter shogaol
    cardamom: aroma releases (k ≈ 0.5 /min) but also boils off (≈ 0.2 /min in an open pan)

TADKA (spices fried in oil)
    aroma release roughly doubles every 15 °C above 170 °C; burning (bitter) starts around 190 °C and
    doubles every 8 °C — and it's the base's hot spot that burns them, which is where LPG's flame ring
    and induction's faster heating differ.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .heat import ROOM, SOURCES, VESSELS, Pot

R = 8.314


def k_at(k100_per_min: float, ea_kj: float, temp_c: float) -> float:
    """Rate per second at temp_c."""
    t = max(temp_c, 0.0) + 273.15
    return k100_per_min / 60 * math.exp(-ea_kj * 1000 / R * (1 / t - 1 / 373.15))


def lpg_word(level: float) -> str:
    return "high flame" if level >= 8.5 else "medium-high" if level >= 6.5 else "medium" if level >= 4.5 \
        else "low" if level >= 2.5 else "sim"


def setting(source_id: str, level: float) -> str:
    s = SOURCES[source_id]
    if s.kind == "lpg":
        return lpg_word(level)
    w, _ = s.watts(level)
    return f"level {round(level)} (~{int(round(w, -2))} W)"


def mmss(sec: float) -> str:
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


# ---------------------------------------------------------------------------------------------- chai
@dataclass
class ChaiRecipe:
    water_g: float = 200
    milk_g: float = 200
    tea_g: float = 6            # CTC tea, ~2 heaped tsp
    sugar_g: float = 16
    ginger_g: float = 5         # crushed fresh ginger (0 = none)
    cardamom_g: float = 1       # ~3 crushed pods
    tea_boil_s: float = 90      # tea leaves boiling in water before milk
    milk_simmer_s: float = 120  # after milk comes back to a boil
    level_boil: float = 10      # bringing water to a boil
    level_tea: float = 6        # while the tea boils
    level_simmer: float = 4     # after milk
    cardamom_last_s: float = 60  # add cardamom this long before the end
    milk_with_water: bool = False  # True = milk and water together from the start (no separate tea boil)

    def public(self) -> dict:
        return asdict(self)


CHAI_BOUNDS = {
    "tea_g": (3, 10), "sugar_g": (0, 35), "ginger_g": (0, 12), "cardamom_g": (0, 2.5),
    "tea_boil_s": (45, 480), "milk_simmer_s": (30, 480), "level_tea": (3, 10), "level_simmer": (2, 8),
    "cardamom_last_s": (0, 240), "milk_g": (100, 300), "water_g": (100, 300),
}


@dataclass
class Extract:
    strength: float = 0.0      # theaflavins, relative units per g tea at full extraction
    caffeine_mg: float = 0.0
    tannin_mg: float = 0.0
    gingerol_mg: float = 0.0
    shogaol_mg: float = 0.0
    aroma: float = 0.0         # cardamom aroma, relative


def _extract_step(e: Extract, r: ChaiRecipe, temp: float, dt: float, tea_in: bool, cardamom_in: bool,
                  boiling: bool) -> None:
    if tea_in and temp > 60:
        e.strength += (r.tea_g * 1.0 - e.strength) * (1 - math.exp(-k_at(0.6, 35, temp) * dt))
        e.caffeine_mg += (r.tea_g * 25 - e.caffeine_mg) * (1 - math.exp(-k_at(0.8, 30, temp) * dt))
        e.tannin_mg += (r.tea_g * 130 - e.tannin_mg) * (1 - math.exp(-k_at(0.12, 50, temp) * dt))
    if r.ginger_g and temp > 50:
        e.gingerol_mg += (r.ginger_g * 2.0 - e.gingerol_mg - e.shogaol_mg) * (1 - math.exp(-k_at(0.35, 30, temp) * dt))
        if boiling:  # gingerol -> shogaol (about twice as pungent) with long boiling
            conv = e.gingerol_mg * (1 - math.exp(-0.02 / 60 * dt))
            e.gingerol_mg -= conv
            e.shogaol_mg += conv
    if cardamom_in:
        e.aroma += (r.cardamom_g - e.aroma) * (1 - math.exp(-k_at(0.5, 25, temp) * dt))
        if boiling:
            e.aroma *= math.exp(-0.2 / 60 * dt)


def simulate_chai(r: ChaiRecipe, source_id: str = "lpg_large", vessel_id: str = "steel_saucepan") -> dict:
    pot = Pot(VESSELS[vessel_id], SOURCES[source_id])
    if not pot.heats():
        return {"error": f"{VESSELS[vessel_id].name} doesn't work on {SOURCES[source_id].name}"}
    e = Extract()
    steps: list[dict] = []
    boil = lambda: pot.t_contents >= 99.5  # noqa: E731

    def run(level: float, seconds: float | None = None, until_boil: bool = False, tea=True, card=False) -> float:
        start = pot.time_s
        limit = seconds if seconds is not None else 1500
        while pot.time_s - start < limit:
            pot.step(level)
            _extract_step(e, r, pot.t_contents, 1.0, tea, card, boil())
            if until_boil and boil():
                break
        return pot.time_s - start

    if r.milk_with_water:
        pot.add("water", r.water_g)
        pot.add("milk", r.milk_g, temp=8)          # from the fridge
        t1 = run(r.level_boil, until_boil=True, tea=False)
        steps.append({"t": 0, "text": f"Put {int(r.water_g)} ml water + {int(r.milk_g)} ml milk"
                      + (f" + {r.ginger_g:g} g crushed ginger" if r.ginger_g else "") +
                      f" on {setting(source_id, r.level_boil)} until it boils", "dur": t1})
    else:
        pot.add("water", r.water_g)
        t1 = run(r.level_boil, until_boil=True, tea=False)
        steps.append({"t": 0, "text": f"Boil {int(r.water_g)} ml water" + (f" with {r.ginger_g:g} g crushed ginger"
                      if r.ginger_g else "") + f" on {setting(source_id, r.level_boil)}", "dur": t1})
    t_tea = pot.time_s
    steps.append({"t": t_tea, "text": f"Add {r.tea_g:g} g tea leaves, boil on {setting(source_id, r.level_tea)}"
                  + ("" if r.milk_with_water else f" for {mmss(r.tea_boil_s)}"), "dur": r.tea_boil_s})
    total_after = r.tea_boil_s if r.milk_with_water else 0
    if not r.milk_with_water:
        run(r.level_tea, r.tea_boil_s)
        pot.add("milk", r.milk_g, temp=8)
        t2 = run(r.level_boil, until_boil=True)
        steps.append({"t": t_tea + r.tea_boil_s, "text": f"Add {int(r.milk_g)} ml milk and {r.sugar_g:g} g sugar; "
                      f"bring back to a boil on {setting(source_id, r.level_boil)} — watch, milk rises", "dur": t2})
    else:
        total_after = r.tea_boil_s
    simmer = r.milk_simmer_s if not r.milk_with_water else total_after
    card_at = max(0.0, simmer - r.cardamom_last_s)
    t_sim = pot.time_s
    run(r.level_simmer, card_at)
    if r.cardamom_g:
        steps.append({"t": pot.time_s, "text": f"Add {r.cardamom_g:g} g crushed cardamom", "dur": 0})
    run(r.level_simmer, simmer - card_at, card=bool(r.cardamom_g))
    steps.insert(len(steps) - (1 if r.cardamom_g else 0),
                 {"t": t_sim, "text": f"Simmer on {setting(source_id, r.level_simmer)} for {mmss(simmer)}", "dur": simmer})
    steps.append({"t": pot.time_s, "text": "Strain and serve", "dur": 0})

    vol_ml = pot.contents.get("water", 0) + pot.contents.get("milk", 0)
    milk_frac = pot.contents.get("milk", 0) / max(vol_ml, 1)
    bound = 0.55 * milk_frac / (milk_frac + 0.2)          # casein binds polyphenols
    free_tannin = e.tannin_mg * (1 - bound) / (vol_ml / 1000)
    return {
        "minutes": round(pot.time_s / 60, 1),
        "volume_ml": round(vol_ml),
        "evaporated_ml": round(pot.evaporated_g),
        "strength": e.strength / (vol_ml / 1000),          # per litre
        "aroma": e.aroma / (vol_ml / 1000),
        "tannin_mg_l": free_tannin,
        "caffeine_mg_l": e.caffeine_mg / (vol_ml / 1000),
        "pungency": (e.gingerol_mg + 2 * e.shogaol_mg) / 294 * 1000 / (vol_ml / 1000),   # µM gingerol-eq
        "sugar_g": r.sugar_g,
        "milk_fat_g": pot.contents.get("milk", 0) * 0.035,
        "mass_g": vol_ml * 1.02,
        "steps": steps,
        "temps": pot.log[::10],
    }


# ---------------------------------------------------------------------------------------------- tadka
@dataclass
class TadkaRecipe:
    oil_g: float = 15          # ghee/oil
    cumin_g: float = 2
    mustard_g: float = 0
    level: float = 7           # heating the oil
    add_at_c: float = 175      # add spices when the oil reaches this
    fry_s: float = 40          # sizzle time before pouring over the dal
    fry_level: float = 5

    def public(self) -> dict:
        return asdict(self)


TADKA_BOUNDS = {"level": (3, 10), "add_at_c": (140, 200), "fry_s": (10, 90), "fry_level": (2, 9)}


def simulate_tadka(r: TadkaRecipe, source_id: str = "lpg_large", vessel_id: str = "iron_kadhai") -> dict:
    pot = Pot(VESSELS[vessel_id], SOURCES[source_id], {"oil": r.oil_g})
    if not pot.heats():
        return {"error": f"{VESSELS[vessel_id].name} doesn't work on {SOURCES[source_id].name}"}
    t_ready = pot.run_until(r.level, r.add_at_c, 900)
    reached = pot.t_contents >= r.add_at_c - 1
    spice = r.cumin_g + r.mustard_g
    aroma = burnt = 0.0
    popped = r.mustard_g == 0
    peak = pot.t_contents
    for _ in range(int(r.fry_s)):
        pot.step(r.fry_level)
        t_oil, t_hot = pot.t_contents, pot.hotspot(r.fry_level)
        peak = max(peak, t_oil)
        k_a = 0.035 * 2 ** ((t_oil - 170) / 15)
        aroma += (1 - aroma) * (1 - math.exp(-k_a))
        # Seeds touching the base feel the hot spot; burning doubles every 8 °C above 190 °C.
        t_burn = 0.7 * t_oil + 0.3 * t_hot
        k_b = 0.0015 * 2 ** ((t_burn - 190) / 8)
        burnt += (1 - burnt) * (1 - math.exp(-k_b))
        if t_oil >= 180:
            popped = True
    return {
        "seconds_to_ready": round(t_ready), "reached": reached, "peak_oil_c": round(peak, 1),
        "aroma": round(aroma * spice, 3), "aroma_fraction": round(aroma, 3), "burnt_fraction": round(burnt, 3),
        "bitter_g": round(burnt * spice * 3.0, 3),     # burnt cumin is strongly bitter (turmeric-eq grams)
        "mustard_popped": popped,
        "steps": [
            {"t": 0, "text": f"Heat {r.oil_g:g} g oil/ghee on {setting(source_id, r.level)}", "dur": t_ready},
            {"t": t_ready, "text": f"At ~{int(r.add_at_c)} °C (a cumin seed sizzles instantly) add "
             f"{r.cumin_g:g} g jeera" + (f" + {r.mustard_g:g} g mustard seeds" if r.mustard_g else ""), "dur": 0},
            {"t": t_ready, "text": f"Turn to {setting(source_id, r.fry_level)}, let it crackle {r.fry_s:g} s, "
             "then pour over the dal", "dur": r.fry_s},
        ],
        "temps": pot.log[::5],
    }
