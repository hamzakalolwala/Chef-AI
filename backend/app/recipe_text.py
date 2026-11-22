"""Turn recipe text (YouTube descriptions and spoken captions) into ingredient amounts.

    "Cumin seeds – ¾ teaspoon"              -> cumin, 0.75 tsp  -> 1.6 g
    "Toor dal – ½ cup (Approx. 100 grams)"  -> toor_dal, 100 g  (an explicit weight wins)
    "...now add half a teaspoon of salt..." -> salt, 0.5 tsp @ 2:31 in the video
    "Salt"  /  "salt to taste"              -> salt, amount unknown ("to taste")

Pure functions, no network: see video_recipe.py for fetching.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}
WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "half": 0.5, "quarter": 0.25}

# unit -> (kind, amount): ml for volumes, g for weights
UNITS: dict[str, tuple[str, float]] = {}
for names, kind, amt in [
    (["teaspoons", "teaspoon", "tea spoons", "tea spoon", "tsps", "tsp", "t"], "ml", 5.0),
    (["tablespoons", "tablespoon", "table spoons", "table spoon", "tbl spoons", "tbl spoon", "tb spoons", "tb spoon",
      "tbsps", "tbsp", "tbs", "tbl", "T"], "ml", 15.0),
    (["cups", "cup"], "ml", 240.0),
    (["millilitres", "milliliters", "millilitre", "milliliter", "ml"], "ml", 1.0),
    (["litres", "liters", "litre", "liter", "ltr"], "ml", 1000.0),
    (["fluid ounces", "fl oz"], "ml", 29.6),
    (["pinches", "pinch"], "ml", 0.3),
    (["dashes", "dash"], "ml", 0.6),
    (["kilograms", "kilogram", "kgs", "kg"], "g", 1000.0),
    (["grams", "gram", "gms", "gm", "grm", "g"], "g", 1.0),
    (["ounces", "ounce", "oz"], "g", 28.35),
    (["pounds", "pound", "lbs", "lb"], "g", 453.6),
    (["sticks", "stick"], "g", 113.0),  # US stick of butter
]:
    for n in names:
        UNITS[n] = (kind, amt)

_NUM = (r"(?:\d+\s+\d+/\d+|\d+(?:\.\d+)?\s*[½¼¾⅓⅔⅛]|\d+/\d+|\d+(?:\.\d+)?|[½¼¾⅓⅔⅛]"
        r"|(?:one|two|three|four|five|\d+)\s+and\s+a\s+half"
        r"|half|quarter|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|an|a)")
_UNIT = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
# qty [- qty] [a|an] unit [.] [of]
QTY_RE = re.compile(
    rf"(?<![\w/])(?P<q1>{_NUM})(?:\s*(?:-|–|to)\s*(?P<q2>{_NUM}))?\s*(?:(?:a|an)\s+)?(?P<u>{_UNIT})(?![a-z])\.?(?:\s+of)?",
    re.IGNORECASE,
)
SERVES_RE = re.compile(r"(?:serves|servings?|yields?|makes)\s*[:\-]?\s*(\d+)|(\d+)\s*(?:servings|people|persons|portions)", re.I)
TO_TASTE_RE = re.compile(r"to taste|as (?:per|needed|required)|as per taste|optional", re.I)
STOP_HEADERS = re.compile(r"^\W*(method|instructions?|directions?|steps?|preparation|procedure|how to|notes?|"
                          r"equipment|follow|subscribe|music|social|connect|website|for business|chapters?|timestamps?)\b",
                          re.I)
INGREDIENTS_HEADER = re.compile(r"\bingredients?\b", re.I)


def normalize(text: str) -> str:
    """'𝗜𝗻𝗴𝗿𝗲𝗱𝗶𝗲𝗻𝘁𝘀' / full-width digits -> plain text, keeping ½ ¼ ¾ (NFKC would turn ½ into '1⁄2')."""
    keep = {c: f"\x00{i}\x00" for i, c in enumerate(FRACTIONS)}
    for c, tok in keep.items():
        text = text.replace(c, tok)
    text = unicodedata.normalize("NFKC", text)
    for c, tok in keep.items():
        text = text.replace(tok, c)
    return text


def parse_number(s: str) -> float | None:
    s = s.strip().lower()
    m = re.fullmatch(r"(\w+)\s+and\s+a\s+half", s)
    if m:
        base = parse_number(m.group(1))
        return None if base is None else base + 0.5
    if s in WORDS:
        return float(WORDS[s])
    m = re.fullmatch(r"(\d+)\s+(\d+)/(\d+)", s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.fullmatch(r"(\d+)/(\d+)", s)
    if m:
        return int(m.group(1)) / int(m.group(2)) if int(m.group(2)) else None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)?\s*([½¼¾⅓⅔⅛])", s)
    if m:
        return float(m.group(1) or 0) + FRACTIONS[m.group(2)]
    try:
        return float(s)
    except ValueError:
        return None


def _unit_key(u: str) -> str:
    if u == "T":
        return "T"  # capital T = tablespoon, lowercase t = teaspoon
    return u.lower() if u.lower() in UNITS else u


@dataclass
class Quantity:
    qty: float
    unit: str
    kind: str          # "ml" | "g"
    amount: float      # ml or g for the whole quantity
    start: int
    end: int


def find_quantities(text: str) -> list[Quantity]:
    out = []
    for m in QTY_RE.finditer(text):
        q1 = parse_number(m.group("q1"))
        q2 = parse_number(m.group("q2")) if m.group("q2") else None
        if q1 is None:
            continue
        qty = (q1 + q2) / 2 if q2 is not None else q1
        unit = _unit_key(m.group("u"))
        if unit not in UNITS:
            continue
        if unit in ("t", "g") and not re.match(r"\d", m.group("q1")):  # "a g…" / "a t…" are words
            continue
        kind, per = UNITS[unit]
        out.append(Quantity(qty, unit, kind, qty * per, m.start(), m.end()))
    return out


@dataclass
class Item:
    ingredient: str | None     # pantry id, or None when we don't know this ingredient
    name: str                  # as written
    qty: float | None
    unit: str | None
    grams: float | None
    to_taste: bool
    source: str                # "description" | "captions"
    time: float | None = None  # seconds into the video, from captions
    raw: str = ""

    def public(self) -> dict:
        return asdict(self)


class AliasMatcher:
    """Longest-alias-wins matching of ingredient names ("coriander powder" before "coriander")."""

    def __init__(self, aliases: dict[str, list[str]]) -> None:
        pairs = sorted(((a.lower(), iid) for iid, al in aliases.items() for a in al), key=lambda p: -len(p[0]))
        self.pairs = pairs
        self.re = re.compile(r"(?<![a-z])(" + "|".join(re.escape(a) for a, _ in pairs) + r")(?![a-z])", re.I)
        self.lookup = dict(pairs)

    def all(self, text: str) -> list[tuple[str, int, int]]:
        return [(self.lookup[m.group(1).lower()], m.start(), m.end()) for m in self.re.finditer(text)]

    def first(self, text: str) -> str | None:
        hits = self.all(text)
        return hits[0][0] if hits else None


def to_grams(q: Quantity, density: float | None) -> float | None:
    if q.kind == "g":
        return round(q.amount, 2)
    return round(q.amount * density, 2) if density else None


def _clean_name(line: str, quantities: list[Quantity]) -> str:
    for q in sorted(quantities, key=lambda q: -q.start):
        line = line[:q.start] + line[q.end:]
    line = re.sub(r"\(.*?\)", "", line)
    line = re.sub(r"^[\s\-–•*·:]+|[\s\-–•*·:,]+$", "", line)
    return re.sub(r"\s{2,}", " ", line)[:60]


def parse_description(text: str, matcher: AliasMatcher, densities: dict[str, float]) -> list[Item]:
    """Ingredient lines from a recipe description ("Cumin seeds – ¾ teaspoon", "1 cup (226g) butter")."""
    lines = [l.strip() for l in normalize(text).splitlines()]
    # Prefer a line that is just "Ingredients" (other lines may be titles like "3 Ingredients Swiss Roll").
    alone = [i for i, l in enumerate(lines) if re.fullmatch(r"\W*ingredients?\W*(?:list)?\W*", l, re.I)]
    loose = [i for i, l in enumerate(lines) if INGREDIENTS_HEADER.search(l) and len(l) < 40 and "http" not in l]
    start = (alone or loose or [-1])[0] + 1
    items: list[Item] = []
    for line in lines[start:]:
        if not line:
            continue
        if start and (STOP_HEADERS.search(line) or re.fullmatch(r"\s*[_=\-—–~*•.]{5,}\s*", line)):
            break
        if "http" in line or line.startswith("#") or len(line) > 140:
            continue
        ing = matcher.first(line)
        qs = find_quantities(line)
        if ing is None and not qs:
            continue
        if not qs and len(line.split()) > 5:  # a method sentence that mentions water/salt, not an ingredient line
            continue
        # Prefer an explicit weight ("½ cup (Approx. 100 grams)").
        q = next((q for q in qs if q.kind == "g"), qs[0] if qs else None)
        density = densities.get(ing) if ing else 0.6
        items.append(Item(
            ingredient=ing,
            name=_clean_name(line, qs) or line[:60],
            qty=q.qty if q else None,
            unit=q.unit if q else None,
            grams=to_grams(q, density) if q else None,
            to_taste=q is None,
            source="description",
            raw=line,
        ))
    return items


def parse_captions(segments: list[tuple[float, str]], matcher: AliasMatcher, densities: dict[str, float]) -> list[Item]:
    """Spoken amounts with timestamps: "...add one and a half teaspoon of salt..." -> salt 1.5 tsp @ t."""
    text, starts = "", []
    for t, s in segments:
        starts.append((len(text), t))
        text += normalize(s).replace("\n", " ") + " "
    def time_at(pos: int) -> float:
        best = 0.0
        for off, t in starts:
            if off > pos:
                break
            best = t
        return best
    items = []
    for q in find_quantities(text):
        window = text[q.end:q.end + 45]
        hits = matcher.all(window)
        if not hits or hits[0][1] > 25:  # ingredient must follow the amount closely
            continue
        ing = hits[0][0]
        items.append(Item(ing, text[q.end:q.end + hits[0][2]].strip(), q.qty, q.unit,
                          to_grams(q, densities.get(ing)), False, "captions", round(time_at(q.start), 1),
                          text[max(0, q.start - 20):q.end + 30].strip()))
    return items


def first_mentions(segments: list[tuple[float, str]], matcher: AliasMatcher) -> dict[str, float]:
    """When each ingredient is first named in the captions (to time "to taste" items)."""
    out: dict[str, float] = {}
    for t, s in segments:
        for ing, _, _ in matcher.all(s):
            out.setdefault(ing, round(t, 1))
    return out


def find_servings(text: str) -> int | None:
    for m in SERVES_RE.finditer(text):
        n = int(m.group(1) or m.group(2))
        if 1 <= n <= 30:
            return n
    return None


def combine(desc: list[Item], caps: list[Item], mentions: dict[str, float]) -> dict:
    """Totals per ingredient. Description amounts win; captions fill gaps and give timing."""
    totals: dict[str, dict] = {}
    for it in desc:
        key = it.ingredient or f"custom:{it.name.lower()}"
        t = totals.setdefault(key, {"ingredient": it.ingredient, "name": it.name, "grams": None, "to_taste": True,
                                    "time": None, "source": "description", "lines": []})
        t["lines"].append(it.raw)
        if it.grams is not None:
            t["grams"] = round((t["grams"] or 0) + it.grams, 2)   # same spice in two sections -> sum
            t["to_taste"] = False
    for it in caps:
        t = totals.get(it.ingredient or "")
        if t is None:
            t = totals.setdefault(it.ingredient or it.name, {"ingredient": it.ingredient, "name": it.name, "grams": None,
                                                             "to_taste": True, "time": None, "source": "captions",
                                                             "lines": []})
        if t["time"] is None:
            t["time"] = it.time
        if t["grams"] is None and it.grams is not None:  # first spoken amount fills a gap
            t["grams"] = it.grams
            t["to_taste"] = False
            t["lines"].append(f"(said in video) {it.raw}")
    for key, t in totals.items():
        if t["time"] is None and t["ingredient"] in mentions:
            t["time"] = mentions[t["ingredient"]]
    return totals
