"""Cheap, per-frame signals computed with plain OpenCV (no ML needed).

* flame  - fraction of bright, saturated blue pixels in the burner zone (gas flames are blue)
* motion - mean frame-to-frame difference in the zone, minus global camera shake / exposure drift
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# OpenCV hue runs 0-180. Gas flame blue sits around 100-130.
BLUE_LO = np.array([95, 70, 90], dtype=np.uint8)
BLUE_HI = np.array([135, 255, 255], dtype=np.uint8)
# Thin-blue fraction (after baseline subtraction) that we treat as "fully lit". A pot hides most of
# the ring, so a small visible arc has to be enough (tuned with tools/simulate.py).
FLAME_FULL_FRACTION = 0.005
# Flames are thin jets/arcs; blue pans, enamel and tiles are big solid blobs. Morphological opening with
# this kernel keeps only the blobs, which we then subtract.
_BLOB_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))


@dataclass(frozen=True)
class Zone:
    """Normalised rectangle (0..1) in camera-frame coordinates."""
    x: float
    y: float
    w: float
    h: float

    def to_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        x0 = int(max(0.0, self.x) * width)
        y0 = int(max(0.0, self.y) * height)
        x1 = int(min(1.0, self.x + self.w) * width)
        y1 = int(min(1.0, self.y + self.h) * height)
        return x0, y0, max(x0 + 1, x1), max(y0 + 1, y1)

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


def decode_jpeg(data: bytes, max_width: int) -> np.ndarray | None:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    if w > max_width:
        scale = max_width / w
        img = cv2.resize(img, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def crop(img: np.ndarray, zone: Zone) -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = zone.to_pixels(w, h)
    return img[y0:y1, x0:x1]


def blue_fraction(bgr: np.ndarray) -> float:
    if bgr.size == 0:
        return 0.0
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BLUE_LO, BLUE_HI)
    blobs = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _BLOB_KERNEL)
    blobs = cv2.dilate(blobs, _BLOB_KERNEL)             # also drop the blob's anti-aliased edge
    thin = cv2.bitwise_and(mask, cv2.bitwise_not(blobs))
    return float(np.count_nonzero(thin)) / float(mask.size)


def flame_score(blue_frac: float, baseline: float) -> float:
    """0..1 flame intensity from the blue fraction, after removing a static blue baseline
    (blue utensils, tiles, etc. measured during calibration with all burners off)."""
    return float(np.clip((blue_frac - baseline) / FLAME_FULL_FRACTION, 0.0, 1.0))


def _small_gray(bgr: np.ndarray) -> np.ndarray:
    g = cv2.cvtColor(cv2.resize(bgr, (64, 64), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(g, (5, 5), 0)


class MotionMeter:
    """Keeps the previous downscaled frame per key and returns mean abs difference (0..1)."""

    def __init__(self) -> None:
        self._prev: dict[str, np.ndarray] = {}

    def measure(self, key: str, bgr: np.ndarray) -> float:
        if bgr.size == 0:
            return 0.0
        g = _small_gray(bgr)
        prev = self._prev.get(key)
        self._prev[key] = g
        if prev is None:
            return 0.0
        return float(np.mean(cv2.absdiff(g, prev))) / 255.0

    def reset(self) -> None:
        self._prev.clear()


# ---------------------------------------------------------------------------------------------
# Lens fog / steam detection
# ---------------------------------------------------------------------------------------------
def sharpness(bgr: np.ndarray) -> float:
    """Variance of the Laplacian on a 320px grey copy: high = crisp edges, low = fogged / blurred."""
    h, w = bgr.shape[:2]
    small = cv2.resize(bgr, (320, max(1, int(h * 320 / w))), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


class ClarityMonitor:
    """Learns how sharp this camera's view normally is, and flags when it drops (steam on the lens).

    While fogged, the backend *holds* each burner's last flame state instead of trusting blurry
    frames (fog washes out the blue flame and would otherwise stop the timers), and pauses dish
    recognition and spoon counting.
    """

    FOG_RATIO = 0.35       # sharpness below 35% of normal = fogged
    CLEAR_RATIO = 0.6      # back above 60% = clear (hysteresis)
    FOG_HOLD = 4.0         # seconds before we call it
    CLEAR_HOLD = 2.0
    WARMUP_FRAMES = 15
    MAX_FOG = 60.0         # never hold longer: the scene may simply have changed (pot taken away)

    def __init__(self) -> None:
        self.baseline: float | None = None
        self.frames = 0
        self.fogged = False
        self.ratio = 1.0
        self._since: float | None = None
        self._fogged_at: float | None = None
        self.expired = False   # last "clear" came from the MAX_FOG timeout, not a sharp view

    def update(self, sharp: float, now: float) -> bool | None:
        """Returns True when fog starts, False when it clears, None otherwise."""
        self.frames += 1
        if self.baseline is None:
            self.baseline = sharp
        # Baseline tracks the sharpest recent views: rises quickly, decays very slowly (lighting changes).
        if sharp > self.baseline:
            self.baseline = 0.7 * self.baseline + 0.3 * sharp
        elif not self.fogged:
            self.baseline = 0.998 * self.baseline + 0.002 * sharp
        self.ratio = sharp / self.baseline if self.baseline > 1e-6 else 1.0
        if self.frames < self.WARMUP_FRAMES:
            return None
        if self.fogged and self._fogged_at is not None and now - self._fogged_at >= self.MAX_FOG:
            # Still "blurry" a minute later: more likely the view itself changed. Relearn and resume.
            self.baseline = sharp
            self.ratio = 1.0
            self.fogged = False
            self._since = self._fogged_at = None
            self.expired = True
            return False
        bad = self.ratio < self.FOG_RATIO if not self.fogged else self.ratio < self.CLEAR_RATIO
        if bad != self.fogged:
            self._since = self._since if self._since is not None else now
            if now - self._since >= (self.FOG_HOLD if bad else self.CLEAR_HOLD):
                self.fogged = bad
                self._since = None
                self._fogged_at = now if bad else None
                self.expired = False
                return bad
        else:
            self._since = None
        return None
