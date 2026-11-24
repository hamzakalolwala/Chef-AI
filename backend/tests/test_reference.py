"""Reference recipes, sweet spot, balance and adaptation. The 'reference' cakes here are made-up test data."""
import base64
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.adapt import adapt
from app.balance import check, grams_of, learn_ranges, ratios
from app.cuts import advise, cook, size_from_words
from app.pantry import Pantry
from app.reference import fingerprint, parse_reference

P = Pantry()

# Three home-style butter cakes (test data): what a "perfect" reference set might look like.
LONG_ROWS = [
    ["Recipe", "Category", "Ingredient", "Quantity", "Unit"],
    ["Test vanilla cake", "Cake", "Maida", "1½", "cups"],
    ["Test vanilla cake", "Cake", "Powdered sugar", "1", "cup"],
    ["Test vanilla cake", "Cake", "Butter", "120", "g"],
    ["Test vanilla cake", "Cake", "Eggs", "2", ""],
    ["Test vanilla cake", "Cake", "Milk", "½", "cup"],
    ["Test vanilla cake", "Cake", "Baking powder", "1.5", "tsp"],
    ["Test vanilla cake", "Cake", "Salt", "1", "pinch"],
    ["Test chocolate cake", "Cake", "Maida", "1.25", "cups"],
    ["Test chocolate cake", "Cake", "Cocoa powder", "¼", "cup"],
    ["Test chocolate cake", "Cake", "Sugar", "1", "cup"],
    ["Test chocolate cake", "Cake", "Oil", "½", "cup"],
    ["Test chocolate cake", "Cake", "Eggs", "2", ""],
    ["Test chocolate cake", "Cake", "Buttermilk", "¾", "cup"],
    ["Test chocolate cake", "Cake", "Baking soda", "1", "tsp"],
    ["Test chocolate cake", "Cake", "Baking powder", "½", "tsp"],
    ["Test marble cake", "Cake", "Maida", "200", "g"],
    ["Test marble cake", "Cake", "Sugar", "180", "g"],
    ["Test marble cake", "Cake", "Butter", "150", "g"],
    ["Test marble cake", "Cake", "Eggs", "3", "nos"],
    ["Test marble cake", "Cake", "Milk", "80", "ml"],
    ["Test marble cake", "Cake", "Baking powder", "2", "tsp"],
]


def xlsx(rows) -> bytes:
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def refs():
    return parse_reference(xlsx(LONG_ROWS), "test_cakes.xlsx", P)


def test_long_sheet_import():
    rs = {r.name: r for r in refs()}
    assert set(rs) == {"Test vanilla cake", "Test chocolate cake", "Test marble cake"}
    assert all(r.category == "cake" for r in rs.values())
    g = grams_of(rs["Test vanilla cake"].items)
    assert g["egg"] == 100 and g["flour"] == pytest.approx(1.5 * 240 * 0.53, rel=0.01)
    assert g["sugar"] > 150 and g["butter"] == 120


def test_wide_csv_and_text_column_import():
    wide = "Recipe,Maida (g),Sugar (g),Butter (g),Eggs,Milk (ml)\nTest sponge,200,170,150,3,60\n".encode()
    r = parse_reference(wide, "wide.csv", P)[0]
    g = grams_of(r.items)
    assert g["flour"] == 200 and g["egg"] == 150 and r.category == "cake"
    text = "Name,Ingredients\nTest shortbread cookies,\"Maida 2 cups; Butter 200 g; Icing sugar ½ cup\"\n".encode()
    r2 = parse_reference(text, "text.csv", P)[0]
    assert r2.category == "cookie" and grams_of(r2.items)["butter"] == 200


def test_fingerprint_and_learned_ranges():
    fp = fingerprint(refs(), P)
    assert fp["cake"]["n"] == 3 and "sweet" in fp
    sw = fp["cake"]["taste"]["sweet"]
    assert sw["lo"] <= sw["mid"] <= sw["hi"] and sw["mid"] > 3
    lo, hi = fp["cake"]["ranges"]["moist_dry"]
    assert lo < hi


def test_extra_cup_of_flour_is_flagged_and_adapter_rebalances():
    rs = refs()
    ranges = learn_ranges([grams_of(r.items) for r in rs], "cake")
    base = grams_of(next(r for r in rs if r.name == "Test vanilla cake").items)
    heavy = {**base, "flour": base["flour"] + 127}           # + 1 cup maida, still 2 eggs
    issues = {i.key for i in check(heavy, "cake", ranges)}
    assert "moist_dry" in issues                              # dry / cakey
    items = [{"ingredient": k, "name": k, "grams": v} for k, v in heavy.items()]
    res = adapt(items, "cake", P, fingerprint(rs, P)["cake"]["taste"], ranges)
    assert res["anchor"] == "flour"
    after = {k for k in (i["key"] for i in res["balance_after"])}
    assert "moist_dry" not in after                           # moisture brought back into her range
    grown = {c["ingredient"] for c in res["changes"] if c["pct"] > 0}
    assert grown & {"milk", "egg", "butter"}                  # compensated with liquids / eggs, not just flour cut


def test_too_sweet_internet_cake_comes_down_to_the_sweet_spot_with_compensation():
    rs = refs()
    fp = fingerprint(rs, P)["cake"]
    sweet = [{"ingredient": "flour", "name": "Maida", "grams": 190}, {"ingredient": "sugar", "name": "Sugar", "grams": 330},
             {"ingredient": "butter", "name": "Butter", "grams": 120}, {"ingredient": "egg", "name": "Eggs", "grams": 100},
             {"ingredient": "milk", "name": "Milk", "grams": 120}, {"ingredient": "baking_powder", "name": "BP", "grams": 6}]
    res = adapt(sweet, "cake", P, fp["taste"], {k: tuple(v) for k, v in fp["ranges"].items()})
    sugar = next(c for c in res["changes"] if c["ingredient"] == "sugar")
    assert sugar["pct"] < -15
    assert abs(res["taste_after"]["sweet"] - fp["taste"]["sweet"]["mid"]) < abs(res["taste_before"]["sweet"] - fp["taste"]["sweet"]["mid"])
    assert res["fit_after"] < res["fit_before"]
    eggs = next(i for i in res["items"] if i["ingredient"] == "egg")["new_grams"]
    assert eggs % 25 == 0                                     # whole / half eggs only


def test_cut_size_changes_fresh_vs_cooked():
    small, big = cook("capsicum", 6, 240), cook("capsicum", 25, 240)
    assert small["fresh"] < big["fresh"] and small["cooked"] > big["cooked"] and small["oil_pickup"] > big["oil_pickup"]
    assert advise("capsicum", 0.9, 240)["best"]["size_mm"] > advise("capsicum", 0.1, 240)["best"]["size_mm"]
    assert size_from_words("1 capsicum, finely chopped") == 3 and size_from_words("capsicum cut in large cubes") == 25


def test_api_import_and_adapt_text():
    from app.main import app
    with TestClient(app) as client:
        r = client.post("/api/reference/import", json={"filename": "test_cakes.xlsx", "replace": True,
                                                        "data_b64": base64.b64encode(xlsx(LONG_ROWS)).decode()})
        assert r.status_code == 200 and len(r.json()["imported"]) == 3
        res = client.post("/api/adapt", json={"name": "Pinterest vanilla cake", "text":
                          "Maida 1.5 cups\nSugar 1.5 cups\nButter 120 g\n2 eggs\nMilk ½ cup\nBaking powder 2 tsp"}).json()
        assert res["category"] == "cake" and res["learned_from"]
        assert any(c["ingredient"] == "sugar" and c["pct"] < 0 for c in res["changes"])
        assert client.post("/api/cuts", json={"veg": "capsicum", "want_fresh": 0.8}).json()["best"]["size_mm"] >= 20
        assert client.post("/api/reference/import", json={"filename": "x.numbers", "data_b64": "AA=="}).status_code == 400
