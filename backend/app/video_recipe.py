"""Read a recipe out of a YouTube video: title, description and captions (no video download).

The cook usually lists amounts in the description and says them out loud; captions also tell us
*when* in the video each ingredient goes in. Result is saved to data/videos/<id>.json so you can
review / correct it before following it at the stove.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from pathlib import Path

from .config import DATA_DIR
from .pantry import Pantry
from .recipe_text import AliasMatcher, combine, find_servings, first_mentions, parse_captions, parse_description

log = logging.getLogger("souschef.video")
VIDEOS_DIR = DATA_DIR / "videos"
ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})")


def video_id(url: str) -> str | None:
    url = url.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    m = ID_RE.search(url)
    return m.group(1) if m else None


def _caption_segments(info: dict) -> tuple[list[tuple[float, str]], str | None]:
    """Prefer creator-written English subs, then auto English in the original language, then auto-translated."""
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    choices = [(k, subs[k], "subtitles") for k in subs if k.startswith("en")]
    choices += [(k, auto[k], "auto") for k in ("en-orig", "en") if k in auto]
    for lang, formats, kind in choices:
        fmt = next((f for f in formats if f.get("ext") == "json3"), None)
        if not fmt:
            continue
        try:
            data = json.loads(urllib.request.urlopen(fmt["url"], timeout=20).read())
        except Exception as e:  # network hiccup / blocked: description alone still works
            log.warning("captions fetch failed: %s", e)
            continue
        segs = [(ev.get("tStartMs", 0) / 1000, "".join(s.get("utf8", "") for s in ev.get("segs", [])))
                for ev in data.get("events", []) if ev.get("segs")]
        segs = [(t, s) for t, s in segs if s.strip()]
        if segs:
            return segs, f"{kind}:{lang}"
    return [], None


def fetch_info(url: str) -> dict:
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
            "js_runtimes": {"node": {}}}
    with yt_dlp.YoutubeDL(opts) as y:
        return y.extract_info(url, download=False)


def build_recipe(info: dict, segments: list[tuple[float, str]], caption_source: str | None, pantry: Pantry) -> dict:
    matcher = AliasMatcher(pantry.alias_map())
    dens = pantry.densities()
    desc = info.get("description") or ""
    desc_items = parse_description(desc, matcher, dens)
    cap_items = parse_captions(segments, matcher, dens) if segments else []
    totals = combine(desc_items, cap_items, first_mentions(segments, matcher) if segments else {})
    items = []
    for key, t in totals.items():
        items.append({
            "ingredient": t["ingredient"],
            "name": pantry.ingredients[t["ingredient"]].name if t["ingredient"] in pantry.ingredients else t["name"],
            "grams": t["grams"],
            "to_taste": t["to_taste"],
            "time": t["time"],
            "source": t["source"],
            "lines": t["lines"][:4],
        })
    items.sort(key=lambda i: (i["time"] is None, i["time"] or 0))
    title = info.get("title") or ""
    return {
        "id": info.get("id"),
        "url": info.get("webpage_url") or f"https://www.youtube.com/watch?v={info.get('id')}",
        "title": title,
        "channel": info.get("channel") or info.get("uploader"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "servings": find_servings(desc) or find_servings(title),
        "caption_source": caption_source,
        "items": items,
        "fetched_at": time.time(),
    }


def fetch_recipe(url: str, pantry: Pantry) -> dict:
    vid = video_id(url)
    if not vid:
        raise ValueError("That doesn't look like a YouTube link")
    info = fetch_info(f"https://www.youtube.com/watch?v={vid}")
    segments, source = _caption_segments(info)
    recipe = build_recipe(info, segments, source, pantry)
    save_recipe(recipe)
    return recipe


def save_recipe(recipe: dict) -> None:
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    (VIDEOS_DIR / f"{recipe['id']}.json").write_text(json.dumps(recipe, indent=2, ensure_ascii=False))


def load_recipe(vid: str) -> dict | None:
    p = VIDEOS_DIR / f"{vid}.json"
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) or not p.exists():
        return None
    return json.loads(p.read_text())


def list_recipes() -> list[dict]:
    if not VIDEOS_DIR.exists():
        return []
    out = []
    for p in sorted(VIDEOS_DIR.glob("*.json"), key=lambda p: -p.stat().st_mtime):
        r = json.loads(p.read_text())
        out.append({k: r.get(k) for k in ("id", "title", "channel", "thumbnail", "url")})
    return out
