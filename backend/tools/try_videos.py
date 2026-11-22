"""Run the recipe reader over real YouTube recipe videos and print what it extracts.

    python tools/try_videos.py                       # built-in sample searches
    python tools/try_videos.py https://youtu.be/...  # specific links
"""
import os
import sys
import tempfile

os.environ.setdefault("TADKA_DATA_DIR", tempfile.mkdtemp(prefix="tadka-videos-"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.pantry import Pantry  # noqa: E402
from app.video_recipe import _caption_segments, build_recipe, fetch_info  # noqa: E402

SEARCHES = ["dal tadka recipe", "masala chai recipe", "chocolate chip cookies recipe", "chicken biryani recipe",
            "poha recipe", "banana bread recipe", "paneer butter masala recipe", "vanilla sponge cake recipe"]

pantry = Pantry()
targets = sys.argv[1:] or [f"ytsearch1:{s}" for s in SEARCHES]
for t in targets:
    try:
        info = fetch_info(t)
        info = info["entries"][0] if "entries" in info else info
        segs, src = _caption_segments(info)
        r = build_recipe(info, segs, src, pantry)
    except Exception as e:
        print(f"\n== {t}: FAILED {e}")
        continue
    known = [i for i in r["items"] if i["ingredient"]]
    amounts = [i for i in known if i["grams"]]
    print(f"\n== {r['title'][:70]}  [{r['id']}]  captions={src}  serves={r['servings']}")
    print(f"   {len(r['items'])} items, {len(known)} matched to pantry, {len(amounts)} with amounts")
    for i in r["items"]:
        when = f"{int(i['time']//60)}:{int(i['time']%60):02d}" if i["time"] is not None else "  -  "
        g = f"{i['grams']:.1f} g" if i["grams"] else ("to taste" if i["to_taste"] else "?")
        print(f"   {when}  {str(i['ingredient'] or '(new)'):18} {i['name'][:26]:26} {g:>10}  [{i['source']}]")
