"""Dish catalog: what the classifier can recognise and how long each dish usually takes."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import BACKEND_DIR, DATA_DIR

# Non-dish classes the classifier also scores. They drive occupancy / lid logic.
EMPTY = "_empty"           # nothing on the burner
EMPTY_VESSEL = "_empty_vessel"
LID = "_lid"               # contents hidden: keep the previous dish guess


@dataclass(frozen=True)
class Dish:
    id: str
    name: str
    minutes: float
    vessel: str            # pot | pan | kadhai | tawa | cooker  (drives the 3D model)
    color: str             # colour of the food surface in the 3D view
    prompts: tuple[str, ...]
    mass_g: float = 800    # cooked weight of one standard batch, for taste concentrations

    def public(self) -> dict:
        d = asdict(self)
        d.pop("prompts")
        return d


@dataclass(frozen=True)
class Catalog:
    dishes: tuple[Dish, ...]
    special: dict[str, tuple[str, ...]]

    def get(self, dish_id: str | None) -> Dish | None:
        if dish_id is None:
            return None
        return next((d for d in self.dishes if d.id == dish_id), None)

    @property
    def dish_ids(self) -> list[str]:
        return [d.id for d in self.dishes]

    def class_prompts(self) -> list[tuple[str, tuple[str, ...]]]:
        """All classes (special + dishes) with their CLIP prompts, in a stable order."""
        return [*self.special.items(), *((d.id, d.prompts) for d in self.dishes)]


def load_catalog(path: Path | None = None) -> Catalog:
    if path is None:
        user = DATA_DIR / "dishes.json"  # your own catalog wins over the bundled one
        path = user if user.exists() else BACKEND_DIR / "data" / "dishes.json"
    raw = json.loads(path.read_text())
    dishes = tuple(
        Dish(
            id=d["id"],
            name=d["name"],
            minutes=float(d["minutes"]),
            vessel=d.get("vessel", "pot"),
            color=d.get("color", "#d9a441"),
            prompts=tuple(d.get("prompts") or [f"{d['name']} cooking on a stove"]),
            mass_g=float(d.get("mass_g", 800)),
        )
        for d in raw["dishes"]
    )
    special = {k: tuple(v) for k, v in raw["special"].items()}
    return Catalog(dishes=dishes, special=special)
