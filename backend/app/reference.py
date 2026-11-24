"""Reference recipes ("my sister's recipes are perfect"): import them, learn your sweet spot and balance.

Import accepts .xlsx / .csv in whatever shape people actually make:
  * long:   one row per ingredient, with columns like Recipe | Ingredient | Quantity | Unit (| Category)
  * wide:   one row per recipe, ingredient names as column headers, amounts in cells
  * text:   a column (or whole sheet) of free text like "Maida – 1½ cups", "Eggs 2", "Sugar 150 g"
Category comes from a Category/Type column if present, otherwise from the recipe name (cake, cookie…).

From the references we learn, per category:
  * taste fingerprint: what the simulated tongue reports for each recipe (sweet, bitter, sour, salty, rich)
    -> your sweet spot is the middle of that, and its spread is how forgiving you are
  * balance ranges: the structure/tenderness/moisture ratios that make *her* recipes work
"""
from __future__ import annotations

import csv
import io
import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .balance import BAKING_KINDS, PIECE_G, grams_of, learn_ranges
from .config import DATA_DIR
from .pantry import Pantry
from .recipe_text import AliasMatcher, find_quantities, normalize, parse_number, to_grams
from .tongue import CHANNELS, Taster, perceive, stimulus

REF_FILE = DATA_DIR / "reference" / "recipes.json"
CATEGORY_WORDS = [
    ("brownie", ["brownie", "blondie"]),
    ("cookie", ["cookie", "biscuit", "nankhatai", "shortbread", "crinkle"]),
    ("muffin", ["muffin"]),
    ("cupcake", ["cupcake"]),
    ("cake", ["cake", "sponge", "loaf", "pound", "tres leches", "cheesecake", "swiss roll"]),
    ("bread", ["bread", "bun", "pav", "pizza dough", "naan", "focaccia"]),
    ("pancake", ["pancake", "waffle", "crepe"]),
    ("dessert", ["kheer", "halwa", "ladoo", "laddu", "barfi", "pudding", "custard", "mousse", "sheera",
                 "gulab", "rabri", "phirni", "shrikhand", "ice cream", "kulfi", "jalebi", "malpua", "dessert"]),
]


def guess_category(name: str, explicit: str | None = None) -> str:
    for txt in (explicit or "", name):
        low = txt.lower()
        for cat, words in CATEGORY_WORDS:
            if any(w in low for w in words) or low.strip() == cat:
                return "cake" if cat == "cupcake" else cat
    return "savoury"


@dataclass
class RefRecipe:
    name: str
    category: str
    items: list[dict] = field(default_factory=list)    # {ingredient, name, grams, raw}
    servings: int | None = None
    source: str = ""

    def public(self) -> dict:
        return {"name": self.name, "category": self.category, "items": self.items, "servings": self.servings,
                "source": self.source}


# ---------------------------------------------------------------------------------------------- parsing
def _item_from_text(text: str, matcher: AliasMatcher, pantry: Pantry, qty_hint: str = "") -> dict | None:
    """'Maida – 1½ cups' / 'Eggs 2' / ingredient + separate quantity cell."""
    text = normalize(str(text)).strip()
    full = f"{text} {normalize(str(qty_hint))}".strip()
    if not full:
        return None
    ing = matcher.first(full)
    qs = find_quantities(full)
    grams = None
    if qs:
        q = next((q for q in qs if q.kind == "g"), qs[0])
        dens = pantry.ingredients[ing].density if ing in pantry.ingredients else 0.6
        grams = to_grams(q, dens)
    elif ing in PIECE_G:      # counted: "Eggs 2", "2 nos"
        m = re.search(r"(\d+(?:\.\d+)?|[½¼¾]|\d+\s*[½¼¾])", full)
        n = parse_number(m.group(1)) if m else None
        grams = n * PIECE_G[ing] if n else None
    if ing is None and grams is None:
        return None
    return {"ingredient": ing, "name": text[:60] or (pantry.ingredients[ing].name if ing else "?"),
            "grams": round(grams, 1) if grams else None, "raw": full[:120]}


def _rows_from_file(data: bytes, filename: str) -> list[tuple[str, list[list[str]]]]:
    """[(sheet name, rows of strings)]"""
    low = filename.lower()
    if low.endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        out = []
        for ws in wb.worksheets:
            rows = [["" if c is None else str(c).strip() for c in r] for r in ws.iter_rows(values_only=True)]
            out.append((ws.title, [r for r in rows if any(r)]))
        return out
    if low.endswith((".csv", ".txt", ".tsv")):
        text = data.decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t") if text.strip() else csv.excel
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect)]
        return [(Path(filename).stem, [r for r in rows if any(r)])]
    raise ValueError("Please export the sheet as .xlsx or .csv (Numbers: File > Export To > Excel)")


def _col(header: list[str], *names: str) -> int | None:
    for i, h in enumerate(header):
        hl = h.lower()
        if any(n in hl for n in names):
            return i
    return None


def parse_reference(data: bytes, filename: str, pantry: Pantry) -> list[RefRecipe]:
    matcher = AliasMatcher(pantry.alias_map())
    recipes: list[RefRecipe] = []
    for sheet, rows in _rows_from_file(data, filename):
        if not rows:
            continue
        header = [h.lower() for h in rows[0]]
        c_recipe = _col(header, "recipe", "dish", "name", "item name")
        c_ing = _col(header, "ingredient", "item", "material")
        c_qty = _col(header, "quantity", "qty", "amount", "measure", "grams", "weight")
        c_unit = _col(header, "unit", "uom")
        c_cat = _col(header, "category", "type", "kind")
        c_serv = _col(header, "serves", "servings", "yield", "pieces")
        c_text = _col(header, "ingredients", "recipe text", "details")
        if c_ing is not None and c_ing == c_recipe:
            c_ing = None
        if c_text is not None and c_ing == c_text:
            # "Ingredients" column: one ingredient per row, or the whole list in one cell? Look at the cells.
            cells = [r[c_text] for r in rows[1:] if c_text < len(r) and r[c_text]]
            listy = sum(1 for c in cells if ";" in c or "\n" in c or len(find_quantities(normalize(c))) > 1)
            if listy >= max(1, len(cells) // 3):
                c_ing = None
            else:
                c_text = None
        if c_ing is not None:                                              # long format
            current: RefRecipe | None = None
            by_name: dict[str, RefRecipe] = {}
            for r in rows[1:]:
                cell = lambda i: r[i] if i is not None and i < len(r) else ""  # noqa: E731
                name = cell(c_recipe) or (current.name if current else sheet)
                if name not in by_name:
                    by_name[name] = RefRecipe(name, guess_category(name, cell(c_cat)), source=f"{filename}:{sheet}")
                current = by_name[name]
                if cell(c_serv):
                    current.servings = int(parse_number(cell(c_serv).split()[0]) or 0) or None
                it = _item_from_text(cell(c_ing), matcher, pantry, f"{cell(c_qty)} {cell(c_unit)}")
                if it:
                    current.items.append(it)
            recipes += [r for r in by_name.values() if r.items]
        elif c_text is not None:                                           # a text column per recipe
            for r in rows[1:]:
                name = r[c_recipe] if c_recipe is not None and c_recipe < len(r) else sheet
                rec = RefRecipe(name, guess_category(name, r[c_cat] if c_cat is not None and c_cat < len(r) else None),
                                source=f"{filename}:{sheet}")
                for line in re.split(r"[\n;]|,(?![^(]*\))", r[c_text] if c_text < len(r) else ""):
                    it = _item_from_text(line, matcher, pantry)
                    if it:
                        rec.items.append(it)
                if rec.items:
                    recipes.append(rec)
        elif c_recipe is not None and sum(1 for h in header if matcher.first(h)) >= 2:   # wide format
            for r in rows[1:]:
                name = r[c_recipe] if c_recipe < len(r) else sheet
                rec = RefRecipe(name, guess_category(name, r[c_cat] if c_cat is not None and c_cat < len(r) else None),
                                source=f"{filename}:{sheet}")
                for i, h in enumerate(rows[0]):
                    if i in (c_recipe, c_cat, c_serv) or i >= len(r) or not r[i] or not matcher.first(h):
                        continue
                    unit_hint = re.search(r"\(([^)]+)\)", h)
                    qty = r[i] if not re.fullmatch(r"[\d.]+", r[i]) or not unit_hint else f"{r[i]} {unit_hint.group(1)}"
                    if re.fullmatch(r"[\d.]+", qty) and matcher.first(h) not in PIECE_G:
                        qty = f"{qty} g"                 # bare numbers in a recipe grid are usually grams
                    it = _item_from_text(re.sub(r"\(.*?\)", "", h), matcher, pantry, qty)
                    if it:
                        rec.items.append(it)
                if rec.items:
                    recipes.append(rec)
        else:                                                              # free text: one recipe per sheet
            rec = RefRecipe(sheet, guess_category(sheet), source=f"{filename}:{sheet}")
            for r in rows:
                it = _item_from_text(" ".join(r), matcher, pantry)
                if it:
                    rec.items.append(it)
            if rec.items:
                recipes.append(rec)
    return recipes


# ---------------------------------------------------------------------------------------------- store
def load_refs() -> list[RefRecipe]:
    if not REF_FILE.exists():
        return []
    return [RefRecipe(**r) for r in json.loads(REF_FILE.read_text())]


def save_refs(refs: list[RefRecipe]) -> None:
    REF_FILE.parent.mkdir(parents=True, exist_ok=True)
    REF_FILE.write_text(json.dumps([r.public() for r in refs], indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------------------------- learning
def taste_of(g: dict[str, float], pantry: Pantry, category: str) -> dict[str, float]:
    names = {i: pantry.ingredients[i].name for i in g if i in pantry.ingredients}
    mass = sum(g.values()) or 1.0
    if category in BAKING_KINDS:          # baked goods lose ~10-15 % water in the oven
        mass *= 0.88
    s = stimulus(g, mass, None if category in BAKING_KINDS else category, names)
    return perceive(Taster(), s)


def fingerprint(refs: list[RefRecipe], pantry: Pantry) -> dict:
    """Per category: the middle and spread of each taste across the reference recipes, plus balance ranges."""
    by_cat: dict[str, list[RefRecipe]] = {}
    for r in refs:
        by_cat.setdefault(r.category, []).append(r)
        if r.category in BAKING_KINDS or r.category == "dessert":
            by_cat.setdefault("sweet", []).append(r)
    out = {}
    for cat, rs in by_cat.items():
        tastes = [taste_of(grams_of(r.items), pantry, r.category) for r in rs]
        fp = {}
        for ch in CHANNELS:
            vs = [t[ch] for t in tastes]
            fp[ch] = {"mid": round(statistics.median(vs), 2), "lo": round(min(vs), 2), "hi": round(max(vs), 2)}
        out[cat] = {"n": len(rs), "recipes": [r.name for r in rs], "taste": fp,
                    "ranges": {k: [round(a, 3), round(b, 3)] for k, (a, b) in
                               learn_ranges([grams_of(r.items) for r in rs], cat).items()} if cat != "sweet" else {}}
    return out
