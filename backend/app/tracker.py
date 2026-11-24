"""Per-burner state machine: turns noisy per-frame signals into cooking sessions.

A *session* starts when a burner's flame comes on, accumulates flame-on seconds, collects
dish evidence from the classifier, counts stirs, and ends once the flame has been off for
`session_gap_seconds`. Finished sessions are handed to `on_session_end` (stored in SQLite).

Nothing here touches images, so the same logic drives the live camera, the demo and the tests.
"""
from __future__ import annotations

import itertools
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from .dishes import EMPTY, EMPTY_VESSEL, LID, Catalog
from .pantry import Pantry
from .taste import forecast
from .tongue import liking, perceive, stimulus, taster_for
from .vision import Zone

# Flame hysteresis
FLAME_ON_SCORE = 0.45
FLAME_OFF_SCORE = 0.15
FLAME_ON_HOLD = 1.5       # s above ON before we call it lit
FLAME_OFF_HOLD = 4.0      # s below OFF before we call it out (pots hide flames briefly)
# Motion
STIR_MOTION = 0.07        # a hand / spoon in the zone
STIR_COOLDOWN = 5.0
STEAM_ALPHA = 0.15
# Classifier smoothing
PROB_ALPHA = 0.35
MIN_DISH_SHARE = 0.22     # evidence share needed before we name a dish
EMPTY_FLAME_SECONDS = 40.0
EMPTY_OCCUPANCY = 0.2      # smoothed P(something on burner) below this = looks empty
MAX_DT = 2.0

_event_ids = itertools.count(1)
# Look-alike jars people grab by mistake.
CONFUSABLE = {"salt": "sugar", "sugar": "salt", "baking_soda": "baking_powder", "baking_powder": "baking_soda",
              "chili": "turmeric", "turmeric": "chili", "cumin": "mustard_seeds", "mustard_seeds": "cumin",
              "flour": "besan", "besan": "flour", "coriander_powder": "cumin"}


@dataclass
class Session:
    started_at: float
    last_tick: float
    last_attention: float
    cook_seconds: float = 0.0
    stirs: int = 0
    evidence: dict[str, float] = field(default_factory=dict)
    override_dish: str | None = None
    override_label: str | None = None
    target_override: float | None = None      # seconds
    flame_off_since: float | None = None
    fired: set[str] = field(default_factory=set)
    demo: bool = False
    batch: float = 1.0                                   # × the recipe's standard batch
    ingredients: dict[str, float] = field(default_factory=dict)   # grams added so far
    log: list[dict] = field(default_factory=list)        # each addition, for undo / history
    follow: dict | None = None                           # a YouTube recipe being followed (see video_recipe.py)


@dataclass
class Burner:
    id: str
    name: str
    zone: Zone
    baseline_blue: float = 0.0
    # live signals
    flame_score: float = 0.0
    flame_auto: bool = False
    flame_manual: bool | None = None     # user override: True/False, None = auto
    motion: float = 0.0
    steam: float = 0.0
    probs: dict[str, float] = field(default_factory=dict)
    last_stir: float | None = None
    _above_since: float | None = None
    _below_since: float | None = None
    _empty_flame_since: float | None = None
    session: Session | None = None
    # remembered between sessions so an override survives a brief flame-off
    pending_override: tuple[str | None, str | None, float | None] | None = None
    pending_follow: dict | None = None

    @property
    def flame_on(self) -> bool:
        return self.flame_manual if self.flame_manual is not None else self.flame_auto

    @property
    def occupied(self) -> float | None:
        if not self.probs:
            return None
        return 1.0 - self.probs.get(EMPTY, 0.0)


class Tracker:
    def __init__(self, catalog: Catalog, *, unattended_minutes: float = 8.0,
                 session_gap_seconds: float = 180.0, clock: Callable[[], float] = time.time,
                 pantry: Pantry | None = None) -> None:
        self.catalog = catalog
        self.pantry = pantry
        self.unattended_seconds = unattended_minutes * 60
        self.session_gap = session_gap_seconds
        self.clock = clock
        self.burners: dict[str, Burner] = {}
        self.events: deque[dict] = deque(maxlen=150)
        self.event_listeners: list[Callable[[dict], None]] = []
        self.session_listeners: list[Callable[[Burner, Session, float], None]] = []

    # -- configuration --------------------------------------------------------------------
    def set_burners(self, specs: list[dict]) -> None:
        """specs: [{id, name, zone:{x,y,w,h}, baseline_blue?}] - keeps sessions of surviving ids."""
        new: dict[str, Burner] = {}
        for s in specs:
            zone = Zone(**s["zone"])
            b = self.burners.get(s["id"])
            if b is None:
                b = Burner(id=s["id"], name=s["name"], zone=zone)
            b.name, b.zone = s["name"], zone
            b.baseline_blue = float(s.get("baseline_blue", b.baseline_blue))
            new[b.id] = b
        for gone in set(self.burners) - set(new):
            self._end_session(self.burners[gone], self.clock())
        self.burners = new

    def burner_specs(self) -> list[dict]:
        return [{"id": b.id, "name": b.name, "zone": b.zone.as_dict(), "baseline_blue": b.baseline_blue}
                for b in self.burners.values()]

    # -- events ---------------------------------------------------------------------------
    def emit(self, burner: Burner | None, kind: str, message: str, level: str = "info",
             extra: dict | None = None) -> dict:
        ev = {"id": next(_event_ids), "ts": self.clock(), "burner_id": burner.id if burner else None,
              "kind": kind, "level": level, "message": message, **(extra or {})}
        self.events.append(ev)
        for fn in self.event_listeners:
            fn(ev)
        return ev

    # -- observations ---------------------------------------------------------------------
    def observe_signals(self, burner_id: str, flame: float, motion: float, now: float | None = None) -> None:
        b = self.burners.get(burner_id)
        if b is None:
            return
        now = self.clock() if now is None else now
        b.flame_score = flame
        b.motion = motion
        b.steam = (1 - STEAM_ALPHA) * b.steam + STEAM_ALPHA * min(1.0, motion / 0.05)

        # flame hysteresis
        if flame >= FLAME_ON_SCORE:
            b._below_since = None
            if b._above_since is None:
                b._above_since = now
            if not b.flame_auto and now - b._above_since >= FLAME_ON_HOLD:
                b.flame_auto = True
        elif flame <= FLAME_OFF_SCORE:
            b._above_since = None
            if b._below_since is None:
                b._below_since = now
            if b.flame_auto and now - b._below_since >= FLAME_OFF_HOLD:
                b.flame_auto = False
        else:
            b._above_since = b._below_since = None

        # stirring = a burst of motion (hand / spoon in the zone)
        if motion >= STIR_MOTION and (b.last_stir is None or now - b.last_stir >= STIR_COOLDOWN):
            b.last_stir = now
            if b.session:
                b.session.stirs += 1
                b.session.last_attention = now
                b.session.fired.discard("unattended")

    def observe_probs(self, burner_id: str, probs: dict[str, float]) -> None:
        b = self.burners.get(burner_id)
        if b is None or not probs:
            return
        if not b.probs:
            b.probs = dict(probs)
        else:
            b.probs = {k: (1 - PROB_ALPHA) * b.probs.get(k, 0.0) + PROB_ALPHA * v for k, v in probs.items()}
        s = b.session
        if s is None or probs.get(LID, 0.0) > 0.5:
            return  # a lid hides the food; keep the previous guess
        dish = {k: v for k, v in probs.items() if not k.startswith("_")}
        total = sum(dish.values())
        if total <= 0:
            return
        weight = 1.0 - probs.get(EMPTY, 0.0) - probs.get(EMPTY_VESSEL, 0.0)
        for k, v in dish.items():
            s.evidence[k] = s.evidence.get(k, 0.0) + weight * v / total

    # -- user actions ---------------------------------------------------------------------
    def set_override(self, burner_id: str, dish_id: str | None, label: str | None,
                     target_minutes: float | None, batch: float | None = None) -> None:
        b = self.burners[burner_id]
        target = target_minutes * 60 if target_minutes else None
        if b.session and batch:
            b.session.batch = batch
        if b.session:
            b.session.override_dish = dish_id
            b.session.override_label = label
            b.session.target_override = target
            b.session.fired.discard("target")
        else:
            b.pending_override = (dish_id, label, target)
        name = label or (self.catalog.get(dish_id).name if dish_id and self.catalog.get(dish_id) else None)
        if name:
            self.emit(b, "override", f"{b.name}: marked as {name}")

    # -- ingredients ----------------------------------------------------------------------
    def ingredient_targets(self, s: Session, profile=None) -> dict[str, float]:
        if not self.pantry:
            return {}
        fallback = self.pantry.targets(self.dish_id(s), s.batch, profile)
        if not s.follow:
            return fallback
        # Following a video: its amounts × your batch scale × your profile. "To taste" items fall back
        # to your own recipe for this dish when there is one.
        prof = profile or self.pantry.profile
        out: dict[str, float] = {}
        for it in s.follow["items"]:
            ing = it.get("ingredient")
            if not ing or ing not in self.pantry.ingredients:
                continue
            if it.get("grams"):
                out[ing] = round(it["grams"] * s.follow["scale"] * prof.factor(ing), 2)
            elif ing in fallback:
                out[ing] = fallback[ing]
        return out

    def set_follow(self, burner_id: str, recipe: dict | None, scale: float = 1.0) -> None:
        """Follow a video recipe on this burner (or stop following with recipe=None)."""
        b = self.burners[burner_id]
        follow = None
        if recipe is not None:
            items = []
            for it in recipe["items"]:
                it = dict(it)
                if not it.get("ingredient") and it.get("grams") and self.pantry:  # e.g. "Chopped ginger"
                    it["ingredient"] = self.pantry.add_custom(it["name"])
                items.append(it)
            follow = {"id": recipe["id"], "title": recipe.get("title") or "", "url": recipe.get("url"),
                      "scale": scale, "items": items}
        if b.session:
            b.session.follow = follow
            b.session.fired = {f for f in b.session.fired if not f.startswith("forgot:")}
        else:
            b.pending_follow = follow
        if follow:
            self.emit(b, "follow", f"{b.name}: following “{follow['title'][:50]}”"
                      + (f" ×{scale:g}" if scale != 1 else ""), "info")

    def _follow_rows(self, s: Session) -> dict | None:
        if not s.follow:
            return None
        targets = self.ingredient_targets(s)
        steps = []
        for it in s.follow["items"]:
            ing = it.get("ingredient")
            added = s.ingredients.get(ing, 0.0) if ing else 0.0
            target = targets.get(ing) if ing else None
            done = bool(added and (target is None or added >= 0.9 * target))
            steps.append({"ingredient": ing, "name": it["name"], "time": it.get("time"), "target": target,
                          "added": added, "done": done, "to_taste": it.get("to_taste", False)})
        nxt = next((st for st in steps if not st["done"] and st["ingredient"]), None)
        return {"id": s.follow["id"], "title": s.follow["title"], "url": s.follow["url"], "scale": s.follow["scale"],
                "steps": steps, "next": nxt}

    def add_ingredient(self, burner_id: str, ingredient: str, grams: float, *, source: str = "manual",
                       amount_label: str | None = None) -> dict:
        """Log an ingredient going into a burner's pot and beep if it overshoots the profile's target."""
        b = self.burners[burner_id]
        s = b.session
        if s is None:
            raise LookupError(f"{b.name} isn't cooking — light it (or set flame On) first")
        assert self.pantry is not None
        ing = self.pantry.ingredients[ingredient]
        before = s.ingredients.get(ingredient, 0.0)
        total = round(before + grams, 2)
        s.ingredients[ingredient] = total
        s.log.append({"ts": self.clock(), "ingredient": ingredient, "grams": grams, "source": source,
                      "label": amount_label})
        s.last_attention = self.clock()
        s.fired.discard("unattended")
        return self._judge_ingredient(b, s, ingredient, before, total, grams, amount_label, source)

    def undo_ingredient(self, burner_id: str) -> dict | None:
        s = self.burners[burner_id].session
        if not s or not s.log:
            return None
        last = s.log.pop()
        s.ingredients[last["ingredient"]] = round(max(0.0, s.ingredients.get(last["ingredient"], 0) - last["grams"]), 2)
        self.emit(self.burners[burner_id], "undo", f"Undid {last['label'] or str(last['grams']) + ' g'} "
                  f"{self.pantry.ingredients[last['ingredient']].name.lower() if self.pantry else ''}".strip())
        return last

    def _judge_ingredient(self, b: Burner, s: Session, ingredient: str, before: float, total: float,
                          grams: float, amount_label: str | None, source: str = "manual") -> dict:
        assert self.pantry is not None
        ing = self.pantry.ingredients[ingredient]
        name = ing.name.lower()
        dish = self.dish_name(s) or (s.follow["title"].split("|")[0].strip()[:30] if s.follow else "the pot")
        prof = self.pantry.profile
        target = self.ingredient_targets(s).get(ingredient)
        added = amount_label or f"{grams:g} g"
        x = {"ingredient": ingredient, "grams": grams}
        if not target:
            targets = self.ingredient_targets(s)
            mixup = CONFUSABLE.get(ingredient)
            if targets and before == 0 and mixup and mixup in targets:
                other = self.pantry.ingredients[mixup].name.lower()
                self.emit(b, "mixup", f"{ing.name} isn't in this recipe — did you mean {other}?", "warn", x)
                return {"total": total, "target": None, "state": "mixup"}
            self.emit(b, "ingredient", f"{b.name}: +{added} {name} ({gr(total)} g total)", extra=x)
            return {"total": total, "target": None, "state": "untracked"}
        limit = target * (1 + prof.tolerance)
        if total > limit and source == "camera" and before < 0.9 * target:
            # One camera-counted spoon jumped past the limit. The camera can't tell a half spoon from a
            # full one, so ask instead of alarming (simulation: this removed most false "too much" beeps).
            self.emit(b, "check_spoon", f"This recipe needs only {gr(target)} g {name} — if that was a full "
                      f"{amount_label.split(' ', 1)[-1] if amount_label else 'spoon'}, it's too much", "warn", x)
            state = "over"
        elif total > limit:
            where = "" if s.follow else f" in {dish}"
            whose = "the video uses" if s.follow else f"{prof.name}'s limit is"
            self.emit(b, "too_much", f"Too much {name}! {gr(total)} g{where} — {whose} {gr(target)} g", "danger", x)
            state = "over"
        elif total >= 0.9 * target and before < 0.9 * target:
            self.emit(b, "ingredient_ok", f"{ing.name} is spot on for {prof.name}: {gr(total)} of {gr(target)} g",
                      "success", x)
            state = "ok"
        else:
            self.emit(b, "ingredient", f"{b.name}: +{added} {name} — {gr(total)} of {gr(target)} g", extra=x)
            state = "ok" if total >= 0.9 * target else "under"
            if total + grams > limit:
                self.emit(b, "careful", f"Careful — another {amount_label or 'spoon'} of {name} "
                          f"would be too much", "warn", x)
        return {"total": total, "target": target, "limit": round(limit, 2), "state": state}

    def dismiss(self, burner_id: str, alert: str) -> None:
        """User says an alert is wrong for this session (e.g. 'there IS a pot on it')."""
        s = self.burners[burner_id].session
        if s is None:
            return
        s.fired.discard(alert)
        s.fired.add(f"{alert}_ok")
        if alert == "empty_flame":
            self.burners[burner_id]._empty_flame_since = None

    def set_manual_flame(self, burner_id: str, on: bool | None) -> None:
        self.burners[burner_id].flame_manual = on

    def reset(self, burner_id: str) -> None:
        b = self.burners[burner_id]
        self._end_session(b, self.clock())
        b.flame_manual = None
        b.pending_override = None
        b.pending_follow = None

    def seed_session(self, burner_id: str, dish_id: str, cook_seconds: float, demo: bool = True) -> None:
        """Start a session part-way through (used by demo mode)."""
        b = self.burners[burner_id]
        now = self.clock()
        b.session = Session(started_at=now - cook_seconds * 1.1, last_tick=now, last_attention=now,
                            cook_seconds=cook_seconds, evidence={dish_id: 5.0}, demo=demo)

    # -- time -----------------------------------------------------------------------------
    def tick(self, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        for b in self.burners.values():
            self._tick_burner(b, now)

    def _tick_burner(self, b: Burner, now: float) -> None:
        s = b.session
        if b.flame_on:
            if s is None:
                s = b.session = Session(started_at=now, last_tick=now, last_attention=now,
                                        evidence={k: v for k, v in b.probs.items() if not k.startswith("_")})
                if b.pending_override:
                    s.override_dish, s.override_label, s.target_override = b.pending_override
                    b.pending_override = None
                if b.pending_follow:
                    s.follow, b.pending_follow = b.pending_follow, None
                self.emit(b, "start", f"{b.name} lit — started timing", "info")
            elif s.flame_off_since is not None:
                self.emit(b, "resume", f"{b.name} back on", "info")
                s.flame_off_since = None
            s.cook_seconds += min(MAX_DT, max(0.0, now - s.last_tick))
        elif s is not None:
            if s.flame_off_since is None:
                s.flame_off_since = now
                self.emit(b, "flame_off", f"{b.name} off after {fmt_duration(s.cook_seconds)}"
                          f" ({self.dish_name(s) or 'unknown dish'})", "info")
            elif now - s.flame_off_since >= self.session_gap:
                self._end_session(b, now)
                return
        if s is None:
            b._empty_flame_since = None
            return
        s.last_tick = now
        self._check_alerts(b, s, now)

    def _check_alerts(self, b: Burner, s: Session, now: float) -> None:
        if not b.flame_on:
            return
        name = self.dish_name(s) or "Food"
        target = self.target_seconds(s)
        if target and s.cook_seconds >= target and "target" not in s.fired:
            s.fired.add("target")
            self.emit(b, "target", f"{name} on {b.name} has cooked {fmt_duration(s.cook_seconds)} — check it",
                      "success")
        if now - s.last_attention >= self.unattended_seconds and "unattended" not in s.fired:
            s.fired.add("unattended")
            mins = int((now - s.last_attention) // 60)
            self.emit(b, "unattended", f"{name} on {b.name} hasn't been stirred in {mins} min", "warn")
        # Someone is logging ingredients but salt/sugar hasn't gone in by half-time.
        if s.log and target and s.cook_seconds >= 0.5 * target:
            for ing in ("salt", "sugar"):
                if self.ingredient_targets(s).get(ing) and not s.ingredients.get(ing) and f"forgot:{ing}" not in s.fired:
                    s.fired.add(f"forgot:{ing}")
                    self.emit(b, "forgot", f"No {ing} in the {name} yet?", "warn", {"ingredient": ing})
        occ = b.occupied
        if occ is not None and occ < EMPTY_OCCUPANCY and "empty_flame_ok" not in s.fired:
            if b._empty_flame_since is None:
                b._empty_flame_since = now
            if now - b._empty_flame_since >= EMPTY_FLAME_SECONDS and "empty_flame" not in s.fired:
                s.fired.add("empty_flame")
                self.emit(b, "empty_flame", f"{b.name} is lit with nothing on it!", "danger")
        else:
            b._empty_flame_since = None
            s.fired.discard("empty_flame")

    def _end_session(self, b: Burner, now: float) -> None:
        s = b.session
        if s is None:
            return
        b.session = None
        b._empty_flame_since = None
        if s.cook_seconds >= 20:
            self.emit(b, "end", f"{b.name}: {self.dish_name(s) or 'session'} finished — "
                      f"{fmt_duration(s.cook_seconds)} on the flame", "info")
            for fn in self.session_listeners:
                fn(b, s, now)

    # -- derived values -------------------------------------------------------------------
    def dish_id(self, s: Session) -> str | None:
        if s.override_dish or s.override_label:
            return s.override_dish
        if not s.evidence:
            return None
        total = sum(s.evidence.values())
        best = max(s.evidence, key=s.evidence.get)
        return best if total > 0 and s.evidence[best] / total >= MIN_DISH_SHARE else None

    def dish_name(self, s: Session) -> str | None:
        if s.override_label:
            return s.override_label
        d = self.catalog.get(self.dish_id(s))
        return d.name if d else None

    def dish_confidence(self, s: Session) -> float:
        if s.override_dish or s.override_label:
            return 1.0
        total = sum(s.evidence.values())
        did = self.dish_id(s)
        return s.evidence[did] / total if did and total else 0.0

    def target_seconds(self, s: Session) -> float | None:
        if s.target_override:
            return s.target_override
        d = self.catalog.get(self.dish_id(s))
        return d.minutes * 60 if d else None

    def dish_mass(self, s: Session) -> float:
        """Cooked weight of this batch: the video's ingredients if it lists the bulk ones, else the dish's."""
        if s.follow:
            total = sum(it.get("grams") or 0 for it in s.follow["items"]) * s.follow["scale"]
            if total >= 300:
                return total
        d = self.catalog.get(self.dish_id(s))
        return (d.mass_g if d else 800.0) * s.batch

    def taste_forecast(self, s: Session) -> list[dict]:
        if not self.pantry or not (s.ingredients or s.follow):
            return []
        return [r.public() for r in forecast(s.ingredients, self.ingredient_targets(s), self.dish_mass(s))]

    def tongue(self, s: Session) -> dict | None:
        """Simulated tongue: what's on it right now, and how each family profile would rate the dish."""
        if not self.pantry or not (s.ingredients or s.follow):
            return None
        dish, mass = self.dish_id(s), self.dish_mass(s)
        names = {i: self.pantry.ingredients[i].name for i in s.ingredients if i in self.pantry.ingredients}
        now = stimulus(s.ingredients, mass, dish, names)
        family = []
        intensity = None
        for p in self.pantry.profiles.values():
            ideal = stimulus(self.ingredient_targets(s, p), mass, dish, names)
            t = taster_for(p.name, ideal)
            felt = perceive(t, now)
            score, complaint, _ = liking(t, felt)
            family.append({"id": p.id, "name": p.name, "emoji": p.emoji, "liking": score, "complaint": complaint,
                           "active": p.id == self.pantry.active_profile})
            if p.id == self.pantry.active_profile:
                intensity = {"now": felt, "ideal": t.ideal}
        return {"intensity": intensity, "family": family}

    def _ingredient_rows(self, s: Session) -> list[dict]:
        return _rows(self.pantry, self.ingredient_targets(s), s.ingredients) if self.pantry else []

    def snapshot(self, now: float | None = None) -> list[dict]:
        now = self.clock() if now is None else now
        out = []
        for b in self.burners.values():
            s = b.session
            dish = self.catalog.get(self.dish_id(s)) if s else None
            target = self.target_seconds(s) if s else None
            top = sorted(((k, v) for k, v in b.probs.items() if not k.startswith("_")),
                         key=lambda kv: -kv[1])[:3]
            top_total = sum(v for k, v in b.probs.items() if not k.startswith("_")) or 1.0
            status = "idle"
            if s and b.flame_on:
                status = "overdue" if target and s.cook_seconds > target else "cooking"
                if "empty_flame" in s.fired:
                    status = "danger"
            elif s:
                status = "paused"
            elif (b.occupied or 0) > 0.6:
                status = "ready"
            out.append({
                "id": b.id,
                "name": b.name,
                "zone": b.zone.as_dict(),
                "status": status,
                "flame": {"on": b.flame_on, "score": round(b.flame_score, 3), "manual": b.flame_manual},
                "motion": round(b.motion, 4),
                "steam": round(b.steam if b.flame_on else b.steam * 0.3, 3),
                "occupied": None if b.occupied is None else round(b.occupied, 3),
                "lid": round(b.probs.get(LID, 0.0), 3),
                "pending_follow": b.pending_follow["title"] if b.pending_follow else None,
                "top": [{"id": k, "name": (self.catalog.get(k).name if self.catalog.get(k) else k),
                         "p": round(v / top_total, 3)} for k, v in top],
                "session": None if s is None else {
                    "started_at": s.started_at,
                    "cook_seconds": round(s.cook_seconds, 1),
                    "target_seconds": target,
                    "progress": round(s.cook_seconds / target, 4) if target else None,
                    "dish_id": dish.id if dish else None,
                    "dish": self.dish_name(s),
                    "vessel": dish.vessel if dish else "pot",
                    "color": dish.color if dish else "#c9a46a",
                    "confidence": round(self.dish_confidence(s), 3),
                    "overridden": bool(s.override_dish or s.override_label),
                    "stirs": s.stirs,
                    "since_attention": round(now - s.last_attention, 1),
                    "flame_off_for": None if s.flame_off_since is None else round(now - s.flame_off_since, 1),
                    "alerts": sorted(a for a in s.fired if ":" not in a),
                    "batch": s.batch,
                    "ingredients": self._ingredient_rows(s),
                    "follow": self._follow_rows(s),
                    "taste": self.taste_forecast(s),
                    "tongue": self.tongue(s),
                },
            })
        return out


def _rows(pantry: Pantry, targets: dict[str, float], added: dict[str, float]) -> list[dict]:
    rows = []
    tol = pantry.profile.tolerance
    for ing_id in list(dict.fromkeys([*targets, *added])):
        ing = pantry.ingredients.get(ing_id)
        if ing is None:
            continue
        g = added.get(ing_id, 0.0)
        t = targets.get(ing_id)
        state = "untracked" if not t else "over" if g > t * (1 + tol) else "ok" if g >= 0.9 * t else "under"
        rows.append({"id": ing_id, "name": ing.name, "color": ing.color, "grams": g, "target": t,
                     "limit": round(t * (1 + tol), 2) if t else None, "state": state})
    return rows


def gr(grams: float) -> str:
    """Grams for people: 63.75 -> '64', 2.25 -> '2.3', 6.0 -> '6'."""
    return f"{grams:.0f}" if grams >= 10 else f"{grams:.1f}".rstrip("0").rstrip(".")


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s" if m else f"{s}s"
