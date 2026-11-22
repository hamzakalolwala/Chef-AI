"""Spoonful detection from printed ArUco markers.

Stick a label (name + marker, printable from the dashboard) on each spice box and on each
spoon's handle. Then a spoonful is:

    spoon marker comes close to an ingredient box  ->  spoon is "loaded" with that ingredient
    the loaded spoon then enters a burner zone      ->  one spoonful into that pot

The markers also give a real-world scale (printed size is known), which is more reliable than
guessing pan dimensions from the brand.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .vision import Zone

DICTIONARY = cv2.aruco.DICT_4X4_50
LOAD_DISTANCE = 2.5     # spoon within 2.5 × marker size of a box = loading
LOAD_TTL = 25.0         # a loaded spoon must reach a pot within this many seconds
REPEAT_GUARD = 3.0      # ignore re-entries into the same pot within this window
LEFT_POT = 2.0          # a spoon must be away from the pot this long between scoops (stirring doesn't count)


@dataclass
class Marker:
    id: int
    x: float      # normalised centre
    y: float
    size: float   # normalised side length


@dataclass
class Spoonful:
    burner_id: str
    ingredient: str | None   # None = a spoon went in but we couldn't tell from which jar
    spoon: str
    inferred: bool = False   # loading frame missed; jar worked out from its label being covered by the hand


@dataclass
class _SpoonState:
    loaded_with: str | None = None
    loaded_at: float = 0.0
    last_drop: dict[str, float] = field(default_factory=dict)
    last_in_pot: float = -1e9
    covered: set[str] = field(default_factory=set)   # jars whose label vanished since this spoon was last in a pot


class MarkerDetector:
    def __init__(self) -> None:
        d = cv2.aruco.getPredefinedDictionary(DICTIONARY)
        self._det = cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters())

    def detect(self, bgr: np.ndarray) -> list[Marker]:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self._det.detectMarkers(gray)
        if ids is None:
            return []
        h, w = gray.shape
        out = []
        for c, i in zip(corners, ids.ravel()):
            pts = c.reshape(4, 2)
            cx, cy = pts.mean(axis=0)
            side = float(np.mean(np.linalg.norm(pts - np.roll(pts, 1, axis=0), axis=1)))
            out.append(Marker(int(i), float(cx / w), float(cy / h), side / max(w, h)))
        return out


def marker_png(marker_id: int, pixels: int = 400) -> bytes:
    d = cv2.aruco.getPredefinedDictionary(DICTIONARY)
    img = cv2.aruco.generateImageMarker(d, marker_id, pixels)
    img = cv2.copyMakeBorder(img, pixels // 8, pixels // 8, pixels // 8, pixels // 8, cv2.BORDER_CONSTANT, value=255)
    return cv2.imencode(".png", img)[1].tobytes()


class SpoonTracker:
    """Turns per-frame marker sightings into spoonful events."""

    def __init__(self, ingredient_markers: dict[int, str], spoon_markers: dict[int, str]) -> None:
        self.ingredient_markers = ingredient_markers
        self.spoon_markers = spoon_markers
        self.state: dict[str, _SpoonState] = {}
        self.known_jars: set[str] = set()

    def update(self, markers: list[Marker], zones: list[tuple[str, Zone]], now: float) -> list[Spoonful]:
        boxes = [(self.ingredient_markers[m.id], m) for m in markers if m.id in self.ingredient_markers]
        present = {ing for ing, _ in boxes}
        self.known_jars |= present
        hidden = self.known_jars - present          # a hand / spoon over the label right now
        for st in self.state.values():
            st.covered |= hidden
        events: list[Spoonful] = []
        for m in markers:
            spoon = self.spoon_markers.get(m.id)
            if spoon is None:
                continue
            st = self.state.setdefault(spoon, _SpoonState())
            # near a box -> load it (nearest box wins)
            near = [(np.hypot(b.x - m.x, b.y - m.y), ing) for ing, b in boxes
                    if np.hypot(b.x - m.x, b.y - m.y) <= LOAD_DISTANCE * max(b.size, m.size)]
            if near:
                st.loaded_with = min(near)[1]
                st.loaded_at = now
                continue
            if st.loaded_with is not None and now - st.loaded_at > LOAD_TTL:
                st.loaded_with = None
            in_zone = next((bid for bid, z in zones if z.x <= m.x <= z.x + z.w and z.y <= m.y <= z.y + z.h), None)
            if in_zone is None:
                continue
            fresh = now - st.last_in_pot >= LEFT_POT        # came back from somewhere, not just stirring
            st.last_in_pot = now
            loaded, inferred = st.loaded_with, False
            if loaded is None and fresh:
                # Didn't catch it at a jar. If exactly one jar's label was covered meanwhile, that's the one;
                # otherwise report an unknown spoonful rather than guess (guessing mislabelled 70% in sim).
                loaded, inferred = (next(iter(st.covered)), True) if len(st.covered) == 1 else (None, False)
                if loaded is None and now - st.last_drop.get(in_zone, -1e9) >= REPEAT_GUARD:
                    events.append(Spoonful(in_zone, None, spoon))
                    st.last_drop[in_zone] = now
            if loaded and now - st.last_drop.get(in_zone, -1e9) >= REPEAT_GUARD:
                events.append(Spoonful(in_zone, loaded, spoon, inferred))
                st.last_drop[in_zone] = now
            st.loaded_with = None
            st.covered = set()
        return events
