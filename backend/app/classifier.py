"""Dish recognition.

ClipClassifier does zero-shot recognition with OpenCLIP: every dish in data/dishes.json is a
set of text prompts, and each burner crop is scored against all of them. No training needed.

It also *learns your kitchen*: whenever you correct a dish in the dashboard, crops of that burner
are saved to data/samples/<dish>/ and turned into a per-dish prototype embedding. Predictions
blend zero-shot scores with similarity to those prototypes, so it gets better at *your* dal in
*your* pot over time.

MockClassifier is used when torch / open_clip aren't installed: it returns no predictions, and
the rest of the system (flame detection, timers, alerts, manual dish labels) keeps working.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np

from .config import DATA_DIR
from .dishes import Catalog

log = logging.getLogger("souschef.classifier")
SAMPLES_DIR = DATA_DIR / "samples"
MAX_SAMPLES_PER_DISH = 60
FEWSHOT_WEIGHT = 0.6


class Classifier:
    name = "mock"
    ready = True

    def classify(self, crops: list[np.ndarray]) -> list[dict[str, float]] | None:
        return None

    def learn(self, dish_id: str, crop: np.ndarray) -> None:
        _save_sample(dish_id, crop)

    def info(self) -> dict:
        return {"name": self.name, "ready": self.ready, "samples": _count_samples()}


def _count_samples() -> dict[str, int]:
    if not SAMPLES_DIR.exists():
        return {}
    return {p.name: len(list(p.glob("*.jpg"))) for p in SAMPLES_DIR.iterdir() if p.is_dir()}


def _save_sample(dish_id: str, crop: np.ndarray) -> Path | None:
    if crop.size == 0:
        return None
    folder = SAMPLES_DIR / dish_id
    folder.mkdir(parents=True, exist_ok=True)
    existing = sorted(folder.glob("*.jpg"))
    for old in existing[: max(0, len(existing) - MAX_SAMPLES_PER_DISH + 1)]:
        old.unlink(missing_ok=True)
    path = folder / f"{int(time.time() * 1000)}.jpg"
    cv2.imwrite(str(path), crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return path


class ClipClassifier(Classifier):
    def __init__(self, catalog: Catalog, model_name: str, pretrained: str) -> None:
        import os

        # Weights are public; don't send a (possibly expired) cached Hugging Face login token.
        os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
        import open_clip
        import torch
        from PIL import Image

        self._torch = torch
        self._Image = Image
        if torch.backends.mps.is_available():
            self.device = "mps"
        elif torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"

        log.info("Loading OpenCLIP %s/%s on %s (first run downloads weights)…", model_name, pretrained, self.device)
        model, _, preprocess = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
        self.model = model.to(self.device).eval()
        self.preprocess = preprocess
        tokenizer = open_clip.get_tokenizer(model_name)

        self.class_ids: list[str] = []
        feats = []
        with torch.no_grad():
            for cid, prompts in catalog.class_prompts():
                tokens = tokenizer(list(prompts)).to(self.device)
                f = self.model.encode_text(tokens).float()
                f = f / f.norm(dim=-1, keepdim=True)
                f = f.mean(0)
                feats.append(f / f.norm())
                self.class_ids.append(cid)
        self.text_feats = torch.stack(feats)          # [C, D]
        self.dish_ids = set(catalog.dish_ids)
        self.prototypes: dict[str, list] = {}          # dish -> list of image embeddings
        self._load_samples()
        self.name = f"clip:{model_name}"
        log.info("OpenCLIP ready with %d classes, %d learned samples", len(self.class_ids),
                 sum(len(v) for v in self.prototypes.values()))

    # -- embeddings -----------------------------------------------------------------------
    def _embed(self, crops: list[np.ndarray]):
        torch = self._torch
        imgs = [self.preprocess(self._Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB))) for c in crops]
        batch = torch.stack(imgs).to(self.device)
        with torch.no_grad():
            f = self.model.encode_image(batch).float()
        return f / f.norm(dim=-1, keepdim=True)

    def _load_samples(self) -> None:
        if not SAMPLES_DIR.exists():
            return
        for folder in SAMPLES_DIR.iterdir():
            if not folder.is_dir() or folder.name not in self.dish_ids:
                continue
            crops = [c for c in (cv2.imread(str(p)) for p in sorted(folder.glob("*.jpg"))) if c is not None]
            if crops:
                self.prototypes[folder.name] = list(self._embed(crops))

    # -- public API -----------------------------------------------------------------------
    def classify(self, crops: list[np.ndarray]) -> list[dict[str, float]] | None:
        crops = [c for c in crops]
        if not crops:
            return []
        torch = self._torch
        img = self._embed(crops)                                   # [N, D]
        zero = (100.0 * img @ self.text_feats.T).softmax(dim=-1)   # [N, C]

        if self.prototypes:
            proto_ids = list(self.prototypes)
            protos = torch.stack([torch.stack(self.prototypes[p]).mean(0) for p in proto_ids])
            protos = protos / protos.norm(dim=-1, keepdim=True)
            few = (100.0 * img @ protos.T).softmax(dim=-1)        # [N, P]
            idx = torch.tensor([self.class_ids.index(p) for p in proto_ids], device=zero.device)
            # Blend only within the mass zero-shot already gave to the learned dishes, so
            # special classes (empty burner, lid) keep their zero-shot probability.
            mass = zero[:, idx].sum(dim=-1, keepdim=True)
            blended = (1 - FEWSHOT_WEIGHT) * zero[:, idx] + FEWSHOT_WEIGHT * few * mass
            zero = zero.clone()
            zero[:, idx] = blended
            zero = zero / zero.sum(dim=-1, keepdim=True)

        rows = zero.cpu().numpy()
        return [dict(zip(self.class_ids, map(float, row))) for row in rows]

    def learn(self, dish_id: str, crop: np.ndarray) -> None:
        if dish_id not in self.dish_ids or _save_sample(dish_id, crop) is None:
            return
        emb = self._embed([crop])[0]
        bucket = self.prototypes.setdefault(dish_id, [])
        bucket.append(emb)
        del bucket[:-MAX_SAMPLES_PER_DISH]


def load_classifier(kind: str, catalog: Catalog, model_name: str, pretrained: str) -> Classifier:
    if kind == "mock":
        return Classifier()
    try:
        return ClipClassifier(catalog, model_name, pretrained)
    except ImportError as exc:
        if kind == "clip":
            raise
        log.warning("OpenCLIP not installed (%s). Running without dish recognition: "
                    "pip install -r requirements-ml.txt to enable it.", exc)
        return Classifier()
