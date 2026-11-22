"""Frame -> per-burner observations, plus the annotated preview frame for the dashboard.

These functions are pure / thread-safe so they can run in a worker thread while the asyncio
loop owns the tracker.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .markers import Marker, MarkerDetector
from .vision import MotionMeter, Zone, blue_fraction, crop, decode_jpeg, flame_score, sharpness


@dataclass
class ZoneObs:
    burner_id: str
    blue: float
    flame: float
    motion: float


@dataclass
class FrameAnalysis:
    frame: np.ndarray
    obs: list[ZoneObs]
    crops: dict[str, np.ndarray]
    markers: list[Marker]
    sharpness: float


class Pipeline:
    def __init__(self, max_width: int) -> None:
        self.max_width = max_width
        self.motion = MotionMeter()
        self.markers = MarkerDetector()

    def analyze(self, jpeg: bytes, zones: list[tuple[str, Zone, float]]) -> FrameAnalysis | None:
        """zones: [(burner_id, zone, baseline_blue)]"""
        frame = decode_jpeg(jpeg, self.max_width)
        if frame is None:
            return None
        global_motion = self.motion.measure("__frame__", frame)
        obs, crops = [], {}
        for bid, zone, baseline in zones:
            c = crop(frame, zone)
            crops[bid] = c
            blue = blue_fraction(c)
            raw_motion = self.motion.measure(bid, c)
            # Subtract most of the whole-frame change (auto exposure, phone wobble).
            motion = max(0.0, raw_motion - 0.8 * global_motion)
            obs.append(ZoneObs(bid, blue, flame_score(blue, baseline), motion))
        return FrameAnalysis(frame, obs, crops, self.markers.detect(frame), sharpness(frame))

    def render(self, frame: np.ndarray, burners: list[dict], markers: list[Marker] | None = None,
               marker_names: dict[int, str] | None = None) -> bytes:
        """Draw burner zones + live labels on the frame (for the dashboard's camera view)."""
        img = frame.copy()
        h, w = img.shape[:2]
        for b in burners:
            x0, y0, x1, y1 = Zone(**b["zone"]).to_pixels(w, h)
            s = b["session"]
            on = b["flame"]["on"]
            color = (60, 200, 255) if on else (170, 170, 170)  # BGR amber vs grey
            if b["status"] == "danger":
                color = (60, 60, 255)
            cv2.rectangle(img, (x0, y0), (x1, y1), color, 2)
            label = b["name"]
            if s:
                mins, secs = divmod(int(s["cook_seconds"]), 60)
                label += f" | {s['dish'] or '?'} {mins:02d}:{secs:02d}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(img, (x0, y0), (x0 + tw + 8, y0 + th + 8), color, -1)
            cv2.putText(img, label, (x0 + 4, y0 + th + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (20, 20, 20), 1,
                        cv2.LINE_AA)
            # flame meter along the bottom edge of the zone
            fx = int(x0 + (x1 - x0) * b["flame"]["score"])
            cv2.line(img, (x0, y1 - 3), (fx, y1 - 3), (255, 160, 40), 4)
        if markers:
            self.render_markers(img, markers, marker_names or {})
        return self._encode(img)

    def render_markers(self, img: np.ndarray, markers: list[Marker], names: dict[int, str]) -> None:
        h, w = img.shape[:2]
        for m in markers:
            cx, cy, r = int(m.x * w), int(m.y * h), int(m.size * max(w, h) * 0.7)
            cv2.circle(img, (cx, cy), r, (80, 220, 120), 2)
            cv2.putText(img, names.get(m.id, f"#{m.id}"), (cx - r, cy - r - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (80, 220, 120), 1, cv2.LINE_AA)

    @staticmethod
    def _encode(img: np.ndarray) -> bytes:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return buf.tobytes() if ok else b""
