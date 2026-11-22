"""Demo mode: feeds scripted, noisy observations into the tracker so the dashboard comes alive
without a phone. Runs through the same tracker code path as the real camera."""
from __future__ import annotations

import asyncio
import math
import random

from .dishes import EMPTY, LID
from .tracker import Tracker

# burner index -> (dish, seconds already cooked, lit at demo-second, off at demo-second)
SCRIPT = [
    ("dal", 12 * 60, 0, None),
    ("chai", 3 * 60 + 20, 0, None),
    ("eggs", 0, 15, 140),
    ("rice", 17 * 60 + 30, 0, None),
]


# demo-second, burner index, ingredient, spoon, count — the dal gets one spoon of salt too many
ADDITIONS = [
    (8, 0, "turmeric", "tsp", 0.5),
    (14, 0, "chili", "tsp", 1),
    (22, 0, "salt", "tsp", 1),
    (40, 0, "salt", "tsp", 1),
    (30, 1, "sugar", "tbsp", 1),
]


def _probs(dish: str | None, catalog_ids: list[str]) -> dict[str, float]:
    p = {k: random.random() * 0.04 for k in catalog_ids}
    if dish is None:
        p[EMPTY] = 0.85
    else:
        p[dish] = 0.55 + random.random() * 0.25
        p[EMPTY] = 0.01
        p[LID] = 0.02
    total = sum(p.values())
    return {k: v / total for k, v in p.items()}


async def run_demo(tracker: Tracker, stop: asyncio.Event) -> None:
    ids = list(tracker.burners)
    class_ids = [*tracker.catalog.special, *tracker.catalog.dish_ids]
    plan = {bid: SCRIPT[i % len(SCRIPT)] for i, bid in enumerate(ids)}
    for bid, (dish, seeded, lit_at, _) in plan.items():
        if seeded and lit_at == 0:
            tracker.seed_session(bid, dish, seeded)
            tracker.burners[bid].flame_auto = True
    t0 = tracker.clock()
    step = 0
    pending = sorted(ADDITIONS)
    while not stop.is_set():
        t = tracker.clock() - t0
        while pending and pending[0][0] <= t and tracker.pantry:
            _, idx, ing, spoon, count = pending.pop(0)
            if idx < len(ids) and tracker.burners[ids[idx]].session:
                grams = tracker.pantry.grams(ing, spoon, count)
                tracker.add_ingredient(ids[idx], ing, grams, source="demo", amount_label=f"{count:g} {spoon}")
        for bid, (dish, _, lit_at, off_at) in plan.items():
            lit = t >= lit_at and (off_at is None or t < off_at)
            base = 0.85 if lit else 0.02
            flame = max(0.0, min(1.0, base + random.uniform(-0.08, 0.08)))
            # simmering bubbles + an occasional stir
            motion = (0.015 + 0.01 * math.sin(t * 1.7 + hash(bid) % 7)) if lit else 0.002
            if lit and random.random() < 0.012:
                motion = 0.1
            tracker.observe_signals(bid, flame, max(0.0, motion))
            if step % 4 == 0:
                on_burner = dish if (lit or (off_at is not None and t >= off_at and t < off_at + 30)) else None
                tracker.observe_probs(bid, _probs(on_burner, class_ids))
        step += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass
