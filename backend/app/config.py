"""Runtime settings, read from environment variables (all prefixed TADKA_)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TADKA_DATA_DIR", BACKEND_DIR / "data"))
WEB_DIST = BACKEND_DIR.parent / "web" / "dist"


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    host: str = os.environ.get("TADKA_HOST", "0.0.0.0")
    port: int = int(os.environ.get("TADKA_PORT", "8000"))
    # auto = CLIP if torch/open_clip are installed, otherwise mock (signals only).
    classifier: str = os.environ.get("TADKA_CLASSIFIER", "auto")
    clip_model: str = os.environ.get("TADKA_CLIP_MODEL", "ViT-B-32")
    clip_pretrained: str = os.environ.get("TADKA_CLIP_PRETRAINED", "laion2b_s34b_b79k")
    classify_interval: float = _float("TADKA_CLASSIFY_INTERVAL", 2.0)
    broadcast_hz: float = _float("TADKA_BROADCAST_HZ", 4.0)
    frame_max_width: int = int(os.environ.get("TADKA_FRAME_WIDTH", "640"))
    unattended_minutes: float = _float("TADKA_UNATTENDED_MIN", 8.0)
    session_gap_seconds: float = _float("TADKA_SESSION_GAP", 180.0)
    demo: bool = os.environ.get("TADKA_DEMO", "0") == "1"


settings = Settings()
