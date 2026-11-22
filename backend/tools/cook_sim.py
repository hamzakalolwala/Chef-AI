"""End-to-end cooking simulator: spoons, camera, beeps, the cook's reactions, and the final taste.

For each simulated dish:
  1. pick a recipe (your pantry recipes) and a cook persona (careful / heavy-handed / eyeballer,
     how full their spoons really are, whether they add "one more for taste", grab the wrong jar,
     and whether they listen to beeps);
  2. every spoon trip is rendered as real camera frames at 2 fps (printed ArUco labels on jars and
     the spoon, motion blur, hands covering the spoon, random angles, JPEG) and goes through the real
     MarkerDetector -> SpoonTracker -> Tracker, which logs grams and beeps;
  3. the cook reacts to the beeps (skips the extra spoon, dilutes an over-salted pot);
  4. the finished dish is tasted with app/taste.py, and compared with the same cook *without* Tadka.

    python tools/cook_sim.py --dishes 120
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass

import cv2
import numpy as np

os.environ.setdefault("TADKA_DATA_DIR", tempfile.mkdtemp(prefix="tadka-cooksim-"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.dishes import load_catalog  # noqa: E402
from app.markers import MarkerDetector, SpoonTracker  # noqa: E402
from app.pantry import Pantry  # noqa: E402
from app.taste import forecast  # noqa: E402
from app.tracker import Tracker  # noqa: E402

W, H = 640, 480
FPS = 2.0   # overridden by --fps
POT_ZONE = {"id": "b1", "name": "Stove", "zone": {"x": 0.45, "y": 0.25, "w": 0.5, "h": 0.65}}
POT_C = (0.70, 0.58)
_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
_MARKER_CACHE: dict[int, np.ndarray] = {}

DISHES = ["dal", "sabzi", "curry", "poha", "chai", "biryani", "kheema", "khichdi", "eggs"]


@dataclass
class Persona:
    name: str
    fill_mean: float      # how full their "1 spoon" really is (1.0 = level)
    fill_sd: float
    extra_salt_p: float   # "one more for taste"
    forget_p: float
    wrong_jar_p: float
    heeds_beeps: float    # probability they act on a warning
    measuring_set: bool   # uses a labelled ½ tsp spoon instead of half-filling a teaspoon


PERSONAS = [
    Persona("careful", 1.0, 0.08, 0.10, 0.05, 0.02, 0.95, True),
    Persona("heavy-handed", 1.35, 0.15, 0.45, 0.05, 0.03, 0.8, False),
    Persona("eyeballer", 1.1, 0.30, 0.35, 0.12, 0.06, 0.7, False),
]


def marker_img(mid: int) -> np.ndarray:
    if mid not in _MARKER_CACHE:
        m = cv2.aruco.generateImageMarker(_DICT, mid, 120)
        _MARKER_CACHE[mid] = cv2.copyMakeBorder(m, 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=255)
    return _MARKER_CACHE[mid]


def paste(img: np.ndarray, mid: int, center: tuple[float, float], size: int, angle: float,
          blur: float, rng: np.random.Generator, occlude: bool) -> None:
    m = marker_img(mid)
    s = size / m.shape[0]
    # rotation + a little perspective shear (sticker seen at an angle)
    sh = rng.uniform(-0.15, 0.15)
    M = cv2.getRotationMatrix2D((m.shape[1] / 2, m.shape[0] / 2), angle, s)
    M[0, 1] += sh * s
    cx, cy = center[0] * W, center[1] * H
    M[0, 2] += cx - m.shape[1] / 2
    M[1, 2] += cy - m.shape[0] / 2
    warped = cv2.warpAffine(m, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=0)
    mask = cv2.warpAffine(np.full_like(m, 255), M, (W, H), flags=cv2.INTER_NEAREST, borderValue=0)
    if blur >= 2:
        k = np.zeros((int(blur), int(blur)), np.float32)
        k[int(blur) // 2, :] = 1.0 / int(blur)
        rot = cv2.getRotationMatrix2D((blur / 2, blur / 2), rng.uniform(0, 180), 1)
        k = cv2.warpAffine(k, rot, k.shape[::-1])
        k /= max(k.sum(), 1e-6)
        warped = cv2.filter2D(warped, -1, k)
        mask = cv2.filter2D(mask, -1, k)
    alpha = (mask.astype(np.float32) / 255.0)[..., None]
    sticker = cv2.cvtColor(warped, cv2.COLOR_GRAY2BGR).astype(np.float32)
    img[:] = (img * (1 - alpha) + sticker * alpha).astype(np.uint8)
    if occlude:  # a hand over part of the spoon sticker
        r = int(size * rng.uniform(0.35, 0.7))
        ox, oy = int(cx + rng.uniform(-0.3, 0.3) * size), int(cy + rng.uniform(-0.3, 0.3) * size)
        cv2.ellipse(img, (ox, oy), (r, int(r * 0.7)), rng.uniform(0, 180), 0, 360, (120, 160, 205), -1)


@dataclass
class Trip:
    ingredient: str       # jar actually used
    spoon: str
    fill: float           # true fullness
    t0: float
    d_jar: float
    d_move: float
    d_pot: float

    @property
    def end(self) -> float:
        return self.t0 + self.d_jar + self.d_move + self.d_pot + 0.5


def spoon_position(tr: Trip, t: float, jar: tuple[float, float], rng: np.random.Generator):
    """Where the spoon is at time t, and how fast it moves (px per frame exposure)."""
    a = t - tr.t0
    pot = (POT_C[0] + rng.uniform(-0.05, 0.05), POT_C[1] + rng.uniform(-0.05, 0.05))
    if a < 0 or t > tr.end:
        return None, 0.0
    if a < tr.d_jar:
        return (jar[0] + rng.uniform(-0.015, 0.035), jar[1] + rng.uniform(0.04, 0.07)), rng.uniform(0, 4)
    a -= tr.d_jar
    if a < tr.d_move:
        k = a / tr.d_move
        return (jar[0] + (pot[0] - jar[0]) * k, jar[1] + (pot[1] - jar[1]) * k), rng.uniform(18, 40)
    a -= tr.d_move
    if a < tr.d_pot:
        return pot, rng.uniform(1, 8)          # tipping / stirring
    return None, 0.0


def plan_trips(recipe: dict[str, float], pantry: Pantry, persona: Persona, rng: np.random.Generator) -> list[Trip]:
    trips, t = [], rng.uniform(3, 8)
    for ing, target in recipe.items():
        if ing not in pantry.ingredients or rng.random() < persona.forget_p:
            continue
        density = pantry.ingredients[ing].density
        spoon = "tsp" if target / (5 * density) <= 3 else "tbsp"
        level_g = pantry.spoons[spoon].ml * density
        n = max(0.5, round(2 * target / level_g) / 2)       # the cook counts level spoons, halves allowed
        if ing == "salt" and rng.random() < persona.extra_salt_p:
            n += 1                                       # "a little more for taste"
        jar = ing
        if ing in ("salt", "sugar") and rng.random() < persona.wrong_jar_p:
            jar = "sugar" if ing == "salt" else "salt"   # look-alike jar
        for k in range(int(np.ceil(n))):
            fill = float(np.clip(rng.normal(persona.fill_mean, persona.fill_sd), 0.5, 2.0))
            use = spoon
            if k + 1 > n:          # the half spoon
                if persona.measuring_set and spoon == "tsp":
                    use = "half_tsp"
                else:
                    fill *= 0.5    # half-filled teaspoon: the camera can't tell
            trips.append(Trip(jar, use, fill, t, rng.uniform(0.5, 2.5), rng.uniform(0.3, 1.2), rng.uniform(0.5, 2.2)))
            t = trips[-1].end + rng.uniform(2, 12)
    return trips


def cook(dish: str, persona: Persona, seed: int, with_tadka: bool, pantry: Pantry, fps: float = 2.0,
         calibrated: bool = False) -> dict:
    rng = np.random.default_rng(seed)
    catalog = load_catalog()
    clock = [0.0]
    tracker = Tracker(catalog, clock=lambda: clock[0], pantry=pantry)
    tracker.set_burners([POT_ZONE])
    tracker.set_override("b1", dish, None, None)
    tracker.set_manual_flame("b1", True)
    tracker.tick(0.0)
    recipe = pantry.targets(dish, 1.0)
    jars = {i: (0.08 + 0.14 * (k % 3), 0.12 + 0.2 * (k // 3)) for k, i in enumerate(sorted({*recipe, "salt", "sugar"}))}
    det = MarkerDetector()
    spoons = SpoonTracker({pantry.ingredients[i].marker: i for i in jars if pantry.ingredients[i].marker is not None},
                          {s.marker: s.id for s in pantry.spoons.values() if s.marker is not None})
    events: list[dict] = []
    tracker.event_listeners.append(events.append)
    base = np.clip(np.full((H, W, 3), (48, 46, 44), np.float32) + rng.normal(0, 8, (H, W, 3)), 0, 255).astype(np.uint8)
    marker_px = int(rng.integers(34, 50))    # 6 cm stickers
    if calibrated:                            # profile knows how full this cook's spoons are
        pantry.profiles[pantry.active_profile].fill = round(persona.fill_mean, 2)
    misattributed = 0.0
    unknown = 0
    wrong_kind: Counter = Counter()

    trips = plan_trips(recipe, pantry, persona, rng)
    true_g: Counter = Counter()
    logged_trips = 0
    skipped: set[str] = set()
    diluted = 1.0
    phase = rng.uniform(0, 1 / FPS)
    for tr in trips:
        if tr.ingredient in skipped:
            continue
        true_g[tr.ingredient] += pantry.spoons[tr.spoon].ml * pantry.ingredients[tr.ingredient].density * tr.fill
        if not with_tadka:
            continue
        n_before = len(events)
        t = phase + np.ceil((tr.t0 - phase) * fps) / fps
        while t <= tr.end:
            clock[0] = t
            img = base.copy()
            pos, speed = spoon_position(tr, t, jars[tr.ingredient], rng)
            scooping = pos is not None and t - tr.t0 < tr.d_jar
            for ing, jpos in jars.items():
                # while scooping, the hand often covers that jar's label
                cover = scooping and ing == tr.ingredient and rng.random() < 0.6
                paste(img, pantry.ingredients[ing].marker, jpos, marker_px, rng.uniform(-8, 8), 0, rng, cover)
            if pos:
                paste(img, pantry.spoons[tr.spoon].marker, pos, int(marker_px * 0.8), rng.uniform(0, 360), speed, rng,
                      occlude=rng.random() < 0.2)
            img = cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])[1], cv2.IMREAD_COLOR)
            for ev in spoons.update(det.detect(img), [("b1", tracker.burners["b1"].zone)], t):
                if ev.ingredient is None:
                    unknown += 1
                    continue
                logged_trips += 1
                grams = pantry.grams(ev.ingredient, ev.spoon, 1.0)
                if ev.ingredient != tr.ingredient:
                    misattributed += 1
                    wrong_kind["inferred" if ev.inferred else "direct"] += 1
                    if os.environ.get("COOKSIM_DEBUG"):
                        print(f"WRONG t={t - tr.t0:5.2f}s into trip (jar {tr.d_jar:.1f}s, move {tr.d_move:.1f}s) "
                              f"trip={tr.ingredient} got={ev.ingredient} spoon={ev.spoon} inferred={ev.inferred}")
                tracker.add_ingredient("b1", ev.ingredient, grams, source="camera", amount_label=f"1 {ev.spoon}")
            t += 1 / fps
        # the cook hears the beeps from this trip
        for ev in events[n_before:]:
            ing = ev.get("ingredient")
            if ev["kind"] == "check_spoon" and tr.fill < 0.75 * persona.fill_mean:
                continue           # "that was only half a spoon" — the cook knows, ignores it
            if ev["kind"] in ("careful", "too_much", "mixup", "ingredient_ok", "check_spoon") and ing \
                    and rng.random() < persona.heeds_beeps:
                skipped.add(ing)
                if ev["kind"] in ("too_much", "check_spoon") and ing == "salt" and diluted == 1.0 \
                        and true_g["salt"] > recipe.get("salt", 0) * 1.15:
                    over = true_g["salt"] / max(recipe.get("salt", 1), 1e-6)
                    diluted = float(min(1.3, max(1.1, over)))     # add water / more dal to rescue it
                if ev["kind"] == "mixup":                      # undo isn't possible, but they switch jars
                    swap = "salt" if ing == "sugar" else "sugar"
                    trips[:] = [Trip(swap, x.spoon, x.fill, x.t0, x.d_jar, x.d_move, x.d_pot) if x.ingredient == ing
                                and x.t0 > tr.t0 else x for x in trips]
    mass = catalog.get(dish).mass_g * diluted
    taste = {r.taste: r for r in forecast(dict(true_g), recipe, mass)}
    logged = tracker.burners["b1"].session.ingredients if tracker.burners["b1"].session else {}
    return {
        "dish": dish, "persona": persona.name, "with_tadka": with_tadka,
        "trips": len([x for x in trips]), "detected": logged_trips, "misattributed": misattributed, "unknown": unknown,
        "wrong_kind": dict(wrong_kind),
        "true_g": dict(true_g), "logged_g": dict(logged), "recipe": recipe,
        "salty": taste["salty"].verdict if "salty" in taste else None,
        "salty_level": taste["salty"].level if "salty" in taste else None,
        "sweet_level": taste["sweet"].level if "sweet" in taste else None,
        "beeps": Counter(e["kind"] for e in events),
        "limit_salt": recipe.get("salt", 0) * (1 + pantry.profile.tolerance),
    }


def run_pair(args: tuple) -> tuple[dict, dict]:
    dish, pi, seed, fps, calibrated = args
    pantry = Pantry()
    pantry.active_profile = "me"
    p = PERSONAS[pi]
    return cook(dish, p, seed, False, pantry, fps), cook(dish, p, seed, True, pantry, fps, calibrated)


def report(pairs: list[tuple[dict, dict]]) -> dict:
    no, yes = [a for a, _ in pairs], [b for _, b in pairs]
    trips = sum(r["trips"] for r in yes)
    det = sum(r["detected"] for r in yes)
    errs = []
    for r in yes:
        for ing, g in r["true_g"].items():
            if g > 0 and ing in r["logged_g"]:
                errs.append(abs(r["logged_g"][ing] - g) / g)
    # beep honesty: was "too much salt" said exactly when the salt really went over the limit?
    tp = fp = fn = 0
    for a, b in pairs:
        truly_over = a["true_g"].get("salt", 0) > a["limit_salt"] > 0
        beeped = b["beeps"].get("too_much", 0) > 0 or b["beeps"].get("careful", 0) > 0
        tp += truly_over and beeped
        fn += truly_over and not beeped
        fp += (not truly_over) and b["beeps"].get("too_much", 0) > 0 and "salt" in str(b["beeps"])
    salted = [(a, b) for a, b in pairs if a["salty_level"]]
    def share(rs, lvl):
        return round(100 * sum(1 for r in rs if r == lvl) / max(1, len(rs)), 1)
    return {
        "dishes": len(pairs),
        "spoon_trips": trips,
        "spoon_detection_%": round(100 * det / max(1, trips), 1),
        "wrong_ingredient_%": round(100 * sum(r["misattributed"] for r in yes) / max(1, det), 1),
        "asked_which_spice_%": round(100 * sum(r["unknown"] for r in yes) / max(1, trips), 1),
        "grams_error_median_%": round(100 * float(np.median(errs)), 1) if errs else None,
        "grams_error_p90_%": round(100 * float(np.percentile(errs, 90)), 1) if errs else None,
        "oversalt_caught": f"{tp}/{tp + fn}",
        "false_too_much_beeps": fp,
        "salt_just_right_%_without": share([a["salty_level"] for a, _ in salted], "ok"),
        "salt_just_right_%_with": share([b["salty_level"] for _, b in salted], "ok"),
        "too_salty_%_without": share([a["salty_level"] for a, _ in salted], "high"),
        "too_salty_%_with": share([b["salty_level"] for _, b in salted], "high"),
    }


if __name__ == "__main__":
    from concurrent.futures import ProcessPoolExecutor

    ap = argparse.ArgumentParser()
    ap.add_argument("--dishes", type=int, default=90)
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--calibrated", action="store_true", help="profile's spoon fullness matches the cook")
    a = ap.parse_args()
    jobs = [(DISHES[i % len(DISHES)], i % len(PERSONAS), i, a.fps, a.calibrated) for i in range(a.dishes)]
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        pairs = list(ex.map(run_pair, jobs))
    for p in PERSONAS:
        sub = [x for x in pairs if x[0]["persona"] == p.name]
        print(f"{p.name:13}", report(sub))
    print("\nALL          ", report(pairs))
    fps_cases = [(a, b) for a, b in pairs if b["beeps"].get("too_much") and not a["true_g"].get("salt", 0) > a["limit_salt"]]
    print(f"\n{len(fps_cases)} 'too much' beeps where the true amount was under the limit, e.g.:")
    for a, b in fps_cases[:8]:
        print(f"  {b['dish']:8} {b['persona']:12} logged={ {k: round(v, 1) for k, v in b['logged_g'].items()} } "
              f"true={ {k: round(v, 1) for k, v in a['true_g'].items()} } recipe={b['recipe']}")
