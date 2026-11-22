"""Randomised stove simulator with ground truth, to measure and tune the vision + tracker.

Each scenario renders a top-down-ish stove at 2 fps for N minutes: burners lit/unlit on a random
schedule (with simmer breaks), pots that hide most of the flame, hands stirring, steam puffs over
pots, a fogged lens episode, camera shake, auto-exposure drift, JPEG noise and a blue pan that is
not a flame. Frames go through the real Pipeline + ClarityMonitor + Tracker, exactly as in the app.

    python tools/simulate.py                 # 12 scenarios, prints a table
    python tools/simulate.py --seeds 40 --minutes 20
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from dataclasses import dataclass, field

import cv2
import numpy as np

os.environ.setdefault("TADKA_DATA_DIR", tempfile.mkdtemp(prefix="tadka-sim-"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.dishes import load_catalog  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402
from app.tracker import Tracker  # noqa: E402
from app.vision import ClarityMonitor  # noqa: E402

W, H = 640, 480
ZONES = [
    {"id": "b1", "name": "Back left", "zone": {"x": 0.06, "y": 0.08, "w": 0.4, "h": 0.4}},
    {"id": "b2", "name": "Back right", "zone": {"x": 0.54, "y": 0.08, "w": 0.4, "h": 0.4}},
    {"id": "b3", "name": "Front left", "zone": {"x": 0.06, "y": 0.52, "w": 0.4, "h": 0.4}},
    {"id": "b4", "name": "Front right", "zone": {"x": 0.54, "y": 0.52, "w": 0.4, "h": 0.4}},
]
CENTERS = [(int((z["zone"]["x"] + z["zone"]["w"] / 2) * W), int((z["zone"]["y"] + z["zone"]["h"] / 2) * H)) for z in ZONES]
FLAME_R = 62
SQUASH = 0.72     # camera ~45° above the stove (recommended mount): circles look like ellipses


def flame_visibility(p: "BurnerPlan") -> float:
    """Fraction of the flame ring not hidden behind the pot, in image space."""
    a = np.linspace(0, 2 * np.pi, 360, endpoint=False)
    x, y = FLAME_R * np.cos(a), FLAME_R * SQUASH * np.sin(a)
    R = p.pot_r + 10
    inside = (x / R) ** 2 + ((y - p.pot_dy) / (R * SQUASH)) ** 2 < 1
    return float(1 - inside.mean())


@dataclass
class BurnerPlan:
    on: list[tuple[float, float]] = field(default_factory=list)       # flame intervals (s)
    pot: tuple[float, float] | None = None                           # pot present interval
    pot_r: int = 60
    pot_dy: int = -10                                                 # perspective: pot sits "above" the ring
    pot_color: tuple[int, int, int] = (150, 150, 155)
    stirs: list[float] = field(default_factory=list)
    steam: list[tuple[float, float]] = field(default_factory=list)

    def lit(self, t: float) -> bool:
        return any(a <= t < b for a, b in self.on)

    def has_pot(self, t: float) -> bool:
        return self.pot is not None and self.pot[0] <= t < self.pot[1]

    @property
    def truth_seconds(self) -> float:
        return sum(b - a for a, b in self.on)


@dataclass
class Scenario:
    seed: int
    minutes: float
    burners: list[BurnerPlan]
    fog: tuple[float, float] | None
    blue_pan: int | None          # burner index holding a blue (unlit) pan for a while
    blue_pan_at: tuple[float, float] | None


def make_scenario(seed: int, minutes: float) -> Scenario:
    rng = np.random.default_rng(seed)
    T = minutes * 60
    plans = []
    for i in range(4):
        # The pot sits on the grate, above the flame, so at ~45° it appears shifted up in the image.
        p = BurnerPlan(pot_r=int(rng.integers(46, 68)), pot_dy=int(rng.integers(-34, -14)),
                       pot_color=tuple(int(c) for c in rng.integers(90, 200, 3)))
        if rng.random() < 0.75:                       # this burner gets used
            start = float(rng.uniform(5, T * 0.4))
            length = float(rng.uniform(T * 0.2, T * 0.55))
            end = min(T - 5, start + length)
            p.pot = (start - rng.uniform(3, 15), end + rng.uniform(5, 30))
            if rng.random() < 0.4 and end - start > 120:   # a simmer break: flame off 20-60 s
                mid = float(rng.uniform(start + 40, end - 80))
                gap = float(rng.uniform(20, 60))
                p.on = [(start, mid), (mid + gap, end)]
            else:
                p.on = [(start, end)]
            t = start + rng.uniform(30, 120)
            while t < end:
                p.stirs.append(float(t))
                t += rng.uniform(45, 200)
            for _ in range(int(rng.integers(1, 4))):
                s = float(rng.uniform(start, end))
                p.steam.append((s, s + rng.uniform(2, 6)))
        plans.append(p)
    fog = None
    if rng.random() < 0.6:
        f = float(rng.uniform(T * 0.3, T * 0.8))
        fog = (f, f + rng.uniform(8, 25))
    idle = [i for i, p in enumerate(plans) if not p.on]
    blue = int(rng.choice(idle)) if idle and rng.random() < 0.6 else None
    blue_at = None
    if blue is not None:
        s = float(rng.uniform(10, T * 0.5))
        blue_at = (s, s + rng.uniform(60, 240))
    return Scenario(seed, minutes, plans, fog, blue, blue_at)


def render(sc: Scenario, t: float, rng: np.random.Generator, base: np.ndarray) -> np.ndarray:
    img = base.copy()
    for i, (p, (cx, cy)) in enumerate(zip(sc.burners, CENTERS)):
        def ell(r: int) -> tuple[int, int]:
            return (r, int(r * SQUASH))
        cv2.ellipse(img, (cx, cy), ell(FLAME_R + 6), 0, 0, 360, (28, 28, 30), 9)       # grate
        cv2.ellipse(img, (cx, cy), ell(26), 0, 0, 360, (60, 110, 160), -1)             # brass cap
        if p.lit(t):
            level = 0.75 + 0.25 * rng.random()                                          # flicker
            col = (int(255 * level), int(150 * level), int(50 * level))
            cv2.ellipse(img, (cx, cy), ell(FLAME_R), 0, 0, 360, col, 5)
        if p.has_pot(t):
            cv2.ellipse(img, (cx, cy + p.pot_dy), ell(p.pot_r + 10), 0, 0, 360, p.pot_color, -1)  # pot body/rim
            cv2.ellipse(img, (cx, cy + p.pot_dy), ell(p.pot_r), 0, 0, 360, (40, 150, 210), -1)    # food
        if sc.blue_pan == i and sc.blue_pan_at and sc.blue_pan_at[0] <= t < sc.blue_pan_at[1]:
            cv2.circle(img, (cx, cy), 70, (190, 90, 30), -1)                             # blue enamel pan, unlit
        for s in p.stirs:                                                                # a hand + spoon, ~3 s
            if s <= t < s + 3:
                k = (t - s) / 3
                hx = int(cx - 90 + 180 * k)
                cv2.ellipse(img, (hx, cy - 20), (40, 26), 20, 0, 360, (120, 160, 210), -1)
                cv2.line(img, (hx, cy - 20), (hx + 30, cy + 10), (60, 60, 60), 5)
        for a, b in p.steam:
            if a <= t < b:
                x0, y0 = max(0, cx - 80), max(0, cy - 110)
                roi = img[y0:cy + 40, x0:cx + 80]
                img[y0:cy + 40, x0:cx + 80] = cv2.addWeighted(cv2.GaussianBlur(roi, (0, 0), 6), 0.6,
                                                              np.full_like(roi, 210), 0.4, 0)
    # global camera effects
    gain = 1.0 + 0.12 * np.sin(t / 37.0)                                 # auto exposure drift
    img = cv2.convertScaleAbs(img, alpha=gain, beta=0)
    dx, dy = rng.normal(0, 0.8, 2)                                       # handheld-ish shake
    img = cv2.warpAffine(img, np.float32([[1, 0, dx], [0, 1, dy]]), (W, H), borderMode=cv2.BORDER_REFLECT)
    if sc.fog and sc.fog[0] <= t < sc.fog[1]:
        img = cv2.addWeighted(cv2.GaussianBlur(img, (0, 0), 10), 0.45, np.full_like(img, 205), 0.55, 0)
    noise = rng.normal(0, 4, img.shape).astype(np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def counter_texture(rng: np.random.Generator) -> np.ndarray:
    base = np.full((H, W, 3), (52, 50, 48), np.uint8)
    speckle = rng.normal(0, 9, (H // 4, W // 4, 1)).astype(np.float32)
    speckle = cv2.resize(speckle, (W, H))[..., None]
    return np.clip(base.astype(np.float32) + speckle, 0, 255).astype(np.uint8)


def run(sc: Scenario, fps: float = 2.0, calibrate: bool = True) -> dict:
    rng = np.random.default_rng(sc.seed + 1000)
    clock = [0.0]
    tr = Tracker(load_catalog(), clock=lambda: clock[0])
    tr.set_burners([dict(z) for z in ZONES])
    pipe = Pipeline(640)
    clarity = ClarityMonitor()
    ended: dict[str, float] = {z["id"]: 0.0 for z in ZONES}
    sessions: dict[str, int] = {z["id"]: 0 for z in ZONES}
    tr.session_listeners.append(lambda b, s, now: ended.__setitem__(b.id, ended[b.id] + s.cook_seconds))
    tr.event_listeners.append(lambda e: e["kind"] == "start" and sessions.__setitem__(e["burner_id"], sessions[e["burner_id"]] + 1))
    base = counter_texture(rng)
    zones = [(b.id, b.zone, b.baseline_blue) for b in tr.burners.values()]
    stirs_detected = {z["id"]: 0 for z in ZONES}
    fog_flagged_at = None
    T = sc.minutes * 60
    n = int(T * fps)
    for f in range(n):
        t = f / fps
        clock[0] = 1000.0 + t
        frame = render(sc, t, rng, base)
        jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()
        a = pipe.analyze(jpeg, zones)
        if calibrate and f == 4:                       # "Capture flame baseline" with everything off
            for o in a.obs:
                if not sc.burners[int(o.burner_id[1]) - 1].lit(t):
                    tr.burners[o.burner_id].baseline_blue = o.blue
            zones = [(b.id, b.zone, b.baseline_blue) for b in tr.burners.values()]
        change = clarity.update(a.sharpness, clock[0])
        if change is True and fog_flagged_at is None:
            fog_flagged_at = t
        if not clarity.fogged:
            for o in a.obs:
                before = tr.burners[o.burner_id].last_stir
                tr.observe_signals(o.burner_id, o.flame, o.motion, clock[0])
                if tr.burners[o.burner_id].last_stir != before:
                    stirs_detected[o.burner_id] += 1
        tr.tick(clock[0])
    out = {"seed": sc.seed, "burners": []}
    for i, b in enumerate(tr.burners.values()):
        p = sc.burners[i]
        measured = ended[b.id] + (b.session.cook_seconds if b.session else 0.0)
        true_stirs = sum(1 for s in p.stirs if s < T)
        out["burners"].append({
            "id": b.id, "truth": round(p.truth_seconds, 1), "visible": round(flame_visibility(p), 2), "measured": round(measured, 1),
            "error": round(measured - p.truth_seconds, 1), "sessions": sessions[b.id],
            "true_sessions": 1 if p.on else 0, "stirs_true": true_stirs, "stirs_seen": stirs_detected[b.id],
        })
    out["fog"] = None if sc.fog is None else {"start": sc.fog[0], "flagged_after": None if fog_flagged_at is None
                                               else round(fog_flagged_at - sc.fog[0], 1)}
    out["fog_false_alarm"] = sc.fog is None and fog_flagged_at is not None
    return out


def _job(a: tuple[int, float, bool]) -> dict:
    return run(make_scenario(a[0], a[1]), calibrate=a[2])


def summarize(results: list[dict]) -> dict:
    lit = [b for r in results for b in r["burners"] if b["truth"] > 0]
    unlit = [b for r in results for b in r["burners"] if b["truth"] == 0]
    rel = [abs(b["error"]) / b["truth"] for b in lit]
    stir_true = sum(b["stirs_true"] for b in lit)
    stir_seen = sum(min(b["stirs_seen"], b["stirs_true"]) for b in lit)
    extra_stirs = sum(max(0, b["stirs_seen"] - b["stirs_true"]) for b in lit + unlit)
    fogs = [r["fog"] for r in results if r["fog"]]
    return {
        "lit_burners": len(lit),
        "timer_err_median_s": float(np.median([abs(b["error"]) for b in lit])) if lit else 0.0,
        "timer_err_max_pct": round(100 * max(rel), 2) if rel else 0.0,
        "missed_visible": sum(1 for b in lit if b["sessions"] == 0 and b["visible"] >= 0.08),
        "hidden_flames": sum(1 for b in lit if b["visible"] < 0.08),
        "missed_hidden": sum(1 for b in lit if b["sessions"] == 0 and b["visible"] < 0.08),
        "split_sessions": sum(1 for b in lit if b["sessions"] > 1),
        "false_sessions": sum(1 for b in unlit if b["sessions"] > 0),
        "stir_recall": round(stir_seen / stir_true, 3) if stir_true else 1.0,
        "extra_stirs": extra_stirs,
        "fog_detected": f"{sum(1 for f in fogs if f['flagged_after'] is not None)}/{len(fogs)}",
        "fog_false_alarms": sum(1 for r in results if r["fog_false_alarm"]),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--minutes", type=float, default=12)
    ap.add_argument("--no-calibrate", action="store_true")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    args = ap.parse_args()
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        results = list(ex.map(_job, [(s, args.minutes, not args.no_calibrate) for s in range(args.seeds)]))
    for s, r in enumerate(results):
        errs = " ".join(f"{b['id']}:{b['measured']:>5.0f}/{b['truth']:<5.0f}s({b['sessions']}) v{b['visible']:.2f}"
                        for b in r["burners"])
        fog = r["fog"] and f"fog+{r['fog']['flagged_after']}s"
        print(f"seed {s:3d}  {errs}  {fog or ''}{' FOG-FALSE-ALARM' if r['fog_false_alarm'] else ''}")
    print("\nSUMMARY", summarize(results))
