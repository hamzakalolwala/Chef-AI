"""Precompute Recipe Lab results for the browser preview (which can't run Python).

    python tools/lab_samples.py   ->  web/src/lib/labSamples.json
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("SOUSCHEF_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.cookchem import ChaiRecipe, TadkaRecipe  # noqa: E402
from app.pantry import Pantry  # noqa: E402
from app.recipe_lab import improve, options  # noqa: E402

p = Pantry()
fam = [p.profiles["me"], p.profiles["mild"]]
HABIT = ChaiRecipe(tea_g=8, tea_boil_s=300, milk_simmer_s=300, level_tea=7, level_simmer=5).public()
out = {"options": options(), "presets": {"chai": HABIT, "tadka": TadkaRecipe(level=10, fry_level=10).public()},
       "results": {}}
for src in ("lpg_large", "induction"):
    out["results"][f"chai:upgrade:{src}"] = improve("chai", HABIT, src, None, fam, "upgrade")
    out["results"][f"chai:new:{src}"] = improve("chai", {}, src, None, fam, "new")
    out["results"][f"tadka:upgrade:{src}"] = improve("tadka", out["presets"]["tadka"], src, None, fam, "upgrade")
for r in out["results"].values():          # keep the preview bundle small
    for side in ("before", "after"):
        r[side]["temps"] = r[side]["temps"][::3]
dest = os.path.join(os.path.dirname(__file__), "..", "..", "web", "src", "lib", "labSamples.json")
with open(dest, "w") as f:
    json.dump(out, f)
print("wrote", os.path.normpath(dest), os.path.getsize(dest) // 1024, "KB")
