"""Cut size: why small capsicum cubes taste different from big ones.

A cube of side a has surface/volume = 6/a, so halving the size doubles the surface per gram:
  * aroma loss   the fresh, green smell (bell-pepper pyrazines, onion sulphur notes) escapes from the
                 surface: loss rate ∝ 6/a                         -> small pieces lose "fresh" fast
  * softening    heat has to reach the centre: time ∝ a² (diffusion), so a 2 cm cube needs ~4× the
                 time of a 1 cm cube to cook through              -> big pieces stay crunchy
  * browning     sweetness / roasted flavour forms on the surface: ∝ surface × time
  * oil pickup   ∝ surface                                        -> small pieces end up oilier

The numbers are calibrated to rough kitchen experience (2 cm capsicum, 4 min stir-fry on high: crisp-tender
with half its fresh crunch), not measured. Use it for direction: "go bigger for a fresher taste".
"""
from __future__ import annotations

import math

# per vegetable: seconds per mm² to soften the core (stir-fry, high heat), how much "fresh" character it has,
# how much it browns/sweetens (sugar), and whether it collapses into the sauce when small.
VEG = {
    "capsicum": {"soften": 0.6, "fresh": 1.0, "brown": 0.8, "melts": False},
    "onion":    {"soften": 0.75, "fresh": 0.7, "brown": 1.0, "melts": True},
    "tomato":   {"soften": 0.35, "fresh": 0.6, "brown": 0.5, "melts": True},
    "carrot":   {"soften": 1.6, "fresh": 0.6, "brown": 0.7, "melts": False},
    "potato":   {"soften": 2.2, "fresh": 0.1, "brown": 0.9, "melts": False},
    "paneer":   {"soften": 0.5, "fresh": 0.0, "brown": 0.9, "melts": False},
    "beans":    {"soften": 1.0, "fresh": 0.8, "brown": 0.5, "melts": False},
}
CUT_WORDS = [("finely chopped", 3), ("minced", 2), ("julienne", 3), ("thinly sliced", 3), ("sliced", 5),
             ("chopped", 8), ("diced", 8), ("small cubes", 10), ("cubed", 15), ("cubes", 15), ("petals", 20),
             ("large cubes", 25), ("chunks", 25), ("big pieces", 25), ("wedges", 25), ("halved", 40)]
METHOD = {"stir_fry": 1.0, "saute": 0.8, "simmer": 0.65, "bake": 0.5}   # how hard the heat hits the surface


def size_from_words(text: str) -> float | None:
    low = text.lower()
    for words, mm in sorted(CUT_WORDS, key=lambda w: -len(w[0])):
        if words in low:
            return float(mm)
    return None


def cook(veg: str, size_mm: float, seconds: float, method: str = "stir_fry") -> dict:
    v = VEG.get(veg, VEG["capsicum"])
    h = METHOD.get(method, 1.0)
    a = max(size_mm, 1.0)
    t_soft = v["soften"] * a * a / h                           # s to cook through to the centre
    done = 1 - math.exp(-seconds / max(t_soft, 1e-6) * 1.2)    # 0 raw .. 1 fully soft
    sv = 6 / a                                                 # per mm
    fresh = v["fresh"] * math.exp(-sv * seconds * h / 140) * (1 - 0.6 * done)
    browned = min(1.0, v["brown"] * sv * seconds * h / 400)
    oil = sv * 2.0                                             # relative oil pickup
    texture = "raw / crunchy" if done < 0.35 else "crisp-tender" if done < 0.7 else "soft" if done < 0.92 else \
        ("melted into the masala" if v["melts"] and a <= 10 else "very soft")
    return {"veg": veg, "size_mm": a, "seconds": seconds, "method": method, "cooked": round(done, 3),
            "fresh": round(fresh, 3), "browned": round(browned, 3), "oil_pickup": round(oil, 3),
            "texture": texture, "seconds_to_cook_through": round(t_soft)}


def advise(veg: str, want_fresh: float, seconds: float, method: str = "stir_fry") -> dict:
    """want_fresh 0 (fully cooked, sweet, soft) .. 1 (fresh, crunchy, green). Pick the size that gets
    closest for the planned cooking time, and show the alternatives."""
    options = [cook(veg, s, seconds, method) for s in (3, 5, 8, 12, 15, 20, 25, 30, 40)]
    best = min(options, key=lambda o: abs(o["fresh"] / max(VEG.get(veg, VEG["capsicum"])["fresh"], 1e-6) - want_fresh)
               + (0.3 if o["cooked"] < 0.3 else 0))
    label = next((w for w, mm in sorted(CUT_WORDS, key=lambda x: abs(x[1] - best["size_mm"]))), "cubes")
    full = max(VEG.get(veg, VEG["capsicum"])["fresh"], 1e-6)
    # If even the best size can't keep it that fresh in this time, say how long to cook it instead.
    time_hint = None
    if best["fresh"] / full < want_fresh - 0.15:
        for t in range(30, int(seconds), 15):
            if cook(veg, best["size_mm"], t, method)["fresh"] / full <= want_fresh:
                time_hint = t
                break
    return {"best": best, "cut_words": label, "options": options, "shorter_time_s": time_hint}
