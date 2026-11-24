"""Ingredients, spoons, recipes and taste profiles.

grams added   = spoonfuls × spoon ml × ingredient density × fill (1.0 level, ~1.5 heaped)
target grams  = recipe grams for the dish × batch size × active profile's multiplier
"""
from __future__ import annotations

import copy
import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import BACKEND_DIR, DATA_DIR

PROFILES_FILE = DATA_DIR / "profiles.json"
DEFAULT_PROFILES = [
    {"id": "me", "name": "Me", "emoji": "🧑‍🍳", "multipliers": {}, "tolerance": 0.15, "fill": 1.0},
    {"id": "mild", "name": "Mild (less salt & chili)", "emoji": "🌿",
     "multipliers": {"salt": 0.7, "chili": 0.5, "sugar": 0.8}, "tolerance": 0.1, "fill": 1.0},
]


@dataclass(frozen=True)
class Ingredient:
    id: str
    name: str
    density: float
    marker: int | None
    color: str
    aliases: tuple[str, ...] = ()
    custom: bool = False     # added at runtime from a video recipe


@dataclass(frozen=True)
class Spoon:
    id: str
    name: str
    ml: float
    marker: int | None


@dataclass
class Profile:
    id: str
    name: str
    emoji: str = "🙂"
    multipliers: dict[str, float] = field(default_factory=dict)   # ingredient -> × recipe
    tolerance: float = 0.15                                        # beep when > target × (1 + tolerance)
    fill: float = 1.0                                              # how full this cook's spoons usually are

    def factor(self, ingredient: str) -> float:
        return float(self.multipliers.get(ingredient, 1.0))


class Pantry:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            user = DATA_DIR / "pantry.json"
            path = user if user.exists() else BACKEND_DIR / "data" / "pantry.json"
        raw = json.loads(path.read_text())
        self.ingredients = {
            i["id"]: Ingredient(id=i["id"], name=i["name"], density=float(i["density"]), marker=i.get("marker"),
                                color=i.get("color", "#cccccc"), aliases=tuple(i.get("aliases") or [i["name"].lower()]))
            for i in raw["ingredients"]}
        self.spoons = {s["id"]: Spoon(**{k: s.get(k) for k in Spoon.__dataclass_fields__}) for s in raw["spoons"]}
        self.recipes: dict[str, dict[str, float]] = raw.get("recipes", {})
        self._lock = threading.Lock()
        self.profiles: dict[str, Profile] = {}
        self.active_profile = "me"
        self._load_profiles()

    def alias_map(self) -> dict[str, list[str]]:
        return {i.id: list(i.aliases) or [i.name.lower()] for i in self.ingredients.values()}

    def densities(self) -> dict[str, float]:
        return {i.id: i.density for i in self.ingredients.values()}

    def add_custom(self, name: str, density: float = 0.6) -> str:
        """An ingredient a video mentions that isn't in the pantry (e.g. 'kasuri methi' if removed)."""
        iid = "x_" + "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")[:30]
        if iid not in self.ingredients:
            self.ingredients[iid] = Ingredient(iid, name[:40].capitalize(), density, None, "#b9b2a6",
                                               (name.lower(),), True)
        return iid

    # -- markers --------------------------------------------------------------------------
    def ingredient_by_marker(self, marker: int) -> Ingredient | None:
        return next((i for i in self.ingredients.values() if i.marker == marker), None)

    def spoon_by_marker(self, marker: int) -> Spoon | None:
        return next((s for s in self.spoons.values() if s.marker == marker), None)

    # -- maths ----------------------------------------------------------------------------
    def grams(self, ingredient: str, spoon: str, count: float = 1.0, fill: float | None = None) -> float:
        ing, sp = self.ingredients[ingredient], self.spoons[spoon]
        f = self.profile.fill if fill is None else fill
        return round(count * sp.ml * ing.density * f, 2)

    def targets(self, dish_id: str | None, batch: float = 1.0, profile: "Profile | None" = None) -> dict[str, float]:
        recipe = self.recipes.get(dish_id or "", {})
        p = profile or self.profile
        return {k: round(v * batch * p.factor(k), 2) for k, v in recipe.items() if k in self.ingredients}

    # -- profiles -------------------------------------------------------------------------
    @property
    def profile(self) -> Profile:
        return self.profiles.get(self.active_profile) or next(iter(self.profiles.values()))

    def _load_profiles(self) -> None:
        data = {"active": "me", "profiles": copy.deepcopy(DEFAULT_PROFILES)}  # never share the defaults' dicts
        if PROFILES_FILE.exists():
            try:
                data = json.loads(PROFILES_FILE.read_text())
            except (OSError, ValueError):
                pass
        self.profiles = {p["id"]: Profile(**p) for p in data["profiles"]}
        self.active_profile = data.get("active") if data.get("active") in self.profiles else next(iter(self.profiles))

    def save_profiles(self, profiles: list[dict], active: str | None = None) -> None:
        with self._lock:
            new = {p["id"]: Profile(**p) for p in profiles}
            if not new:
                raise ValueError("need at least one profile")
            self.profiles = new
            if active in new:
                self.active_profile = active
            elif self.active_profile not in new:
                self.active_profile = next(iter(new))
            self._persist()

    RATING_DRIVERS = {"salty": ["salt"], "heat": ["chili"], "sweet": ["sugar", "brown_sugar", "honey"],
                      "rich": ["oil", "ghee", "butter"]}

    def learn_from_rating(self, pid: str, ratings: dict[str, str], step: float = 0.1) -> dict[str, float]:
        """After eating: 'too much' -> this person wants ~10% less next time, 'too little' -> ~10% more."""
        with self._lock:
            p = self.profiles[pid]
            for taste, verdict in ratings.items():
                k = {"too much": 1 - step, "too little": 1 + step}.get(verdict)
                if k is None:
                    continue
                for ing in self.RATING_DRIVERS.get(taste, []):
                    p.multipliers[ing] = round(min(2.5, max(0.2, p.factor(ing) * k)), 3)
            self._persist()
            return dict(p.multipliers)

    def set_active(self, pid: str) -> None:
        if pid not in self.profiles:
            raise KeyError(pid)
        self.active_profile = pid
        self._persist()

    def _persist(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PROFILES_FILE.write_text(json.dumps(
            {"active": self.active_profile, "profiles": [asdict(p) for p in self.profiles.values()]}, indent=2))

    def public(self) -> dict:
        return {
            "ingredients": [asdict(i) for i in self.ingredients.values()],
            "spoons": [asdict(s) for s in self.spoons.values()],
            "recipes": self.recipes,
            "profiles": [asdict(p) for p in self.profiles.values()],
            "active_profile": self.active_profile,
        }
