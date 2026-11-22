"""Recipe reading, using text patterns taken from real YouTube recipe descriptions/captions."""
import pytest

from app.pantry import Pantry
from app.recipe_text import AliasMatcher, combine, find_quantities, find_servings, normalize, parse_captions, parse_description
from app.video_recipe import build_recipe, video_id

P = Pantry()
M = AliasMatcher(P.alias_map())
D = P.densities()

DAL = """#DalTadka #DalFry
Ingredients
Toor dal – ½ cup (Approx. 100 grams)
Moong dal – 2 tbl spoon
Onion – 1
Turmeric powder
Ghee – 2½ tb spoon
Cumin seeds – ¾ teaspoon
Dry chilli – 3
Chilli powder – ½ teaspoon
Coriander seeds – 2 teaspoon
Coriander leaves
Salt

Method
1. Wash the dal, drain the water and pressure cook with salt and turmeric for 3 whistles."""


def by_ing(items):
    return {i.ingredient: i for i in items if i.ingredient}


@pytest.mark.parametrize("text,qty,unit", [
    ("½ cup", 0.5, "cup"), ("2½ tb spoon", 2.5, "tb spoon"), ("1 1/2 tsp", 1.5, "tsp"), ("1/3cup", 1 / 3, "cup"),
    ("half a teaspoon", 0.5, "teaspoon"), ("one and a half teaspoon", 1.5, "teaspoon"), ("2-3 tbsp", 2.5, "tbsp"),
    ("10 to 15 g", 12.5, "g"), ("a pinch", 1, "pinch"), ("1 T", 1, "T"), ("1 t", 1, "t"), ("200gms", 200, "gms"),
])
def test_quantities(text, qty, unit):
    q = find_quantities(text)[0]
    assert q.qty == pytest.approx(qty) and q.unit == unit


def test_no_false_quantities():
    assert find_quantities("a great recipe for tea time") == []
    assert find_quantities("Temperature 160°c ( 25 - 30 minutes )") == []


def test_dal_description():
    items = by_ing(parse_description(DAL, M, D))
    assert items["toor_dal"].grams == 100            # explicit weight beats "½ cup"
    assert items["ghee"].grams == pytest.approx(2.5 * 15 * 0.9)
    assert items["cumin"].grams == pytest.approx(0.75 * 5 * 0.42, abs=0.01)
    assert items["salt"].to_taste and items["turmeric"].to_taste
    assert "coriander_seeds" in items and items["coriander_leaves"].to_taste   # seeds ≠ leaves
    assert "chili" in items and items["chili"].qty == 0.5                     # chilli powder, not "Dry chilli"
    assert "water" not in items                                              # method sentence ignored


def test_fancy_unicode_header_and_divider():
    text = "3 𝗜𝗻𝗴𝗿𝗲𝗱𝗶𝗲𝗻𝘁𝘀 𝗦𝘄𝗶𝘀𝘀 𝗥𝗼𝗹𝗹 ,\nhttps://youtu.be/x\n1𝗞𝗚 𝗖𝗵𝗼𝗰𝗼𝗹𝗮𝘁𝗲 𝗦𝗽𝗼𝗻𝗴𝗲 𝗖𝗮𝗸𝗲\n" \
           "INGREDIENTS\n80 g ( powdered sugar / white sugar ) 1/3cup\n80 g ( cake flour )1/2cup\n" \
           "________________\n✅Chocolate muffins 2 cups flour"
    items = by_ing(parse_description(text, M, D))
    assert set(items) == {"sugar", "flour"} and items["flour"].grams == 80


def test_cookie_style_lines():
    text = "Ingredients:\n1 cup (226g) unsalted butter, melted\n2 1/4 cups all-purpose flour\n1 tsp baking soda\n" \
           "1/2 tsp baking powder\n1 cup brown sugar\nServes 24"
    items = by_ing(parse_description(text, M, D))
    assert items["butter"].grams == 226
    assert items["flour"].grams == pytest.approx(2.25 * 240 * 0.53)
    assert "baking_soda" in items and "baking_powder" in items and "brown_sugar" in items  # not plain sugar/powder
    assert find_servings(text) == 24


def test_captions_amounts_and_times():
    segs = [(10.0, "so first i'm going to add"), (12.5, "one and a half teaspoon of salt"),
            (40.0, "then half a teaspoon of haldi"), (70.0, "and a pinch of hing goes in")]
    items = by_ing(parse_captions(segs, M, D))
    assert items["salt"].grams == pytest.approx(9.0) and items["salt"].time == 12.5
    assert items["turmeric"].time == 40.0
    assert items["hing"].unit == "pinch"


def test_captions_fill_to_taste_gaps_and_give_timing():
    desc = parse_description("Ingredients\nSalt\nGhee – 2 tbsp", M, D)
    caps = parse_captions([(30.0, "add 1 teaspoon salt"), (5.0, "")], M, D)
    totals = combine(desc, caps, {"ghee": 20.0})
    assert totals["salt"]["grams"] == 6.0 and totals["salt"]["time"] == 30.0
    assert totals["ghee"]["grams"] == 27.0 and totals["ghee"]["time"] == 20.0


def test_same_spice_in_two_sections_is_summed():
    totals = combine(parse_description("Ingredients\nFor dal:\nGhee – 1 tbsp\nFor tadka:\nGhee – 1 tbsp", M, D), [], {})
    assert totals["ghee"]["grams"] == 27.0


def test_build_recipe_and_video_ids():
    info = {"id": "abcdefghijk", "title": "Dal tadka | serves 4 people", "description": DAL}
    r = build_recipe(info, [], None, P)
    names = {i["ingredient"] for i in r["items"]}
    assert {"toor_dal", "salt", "ghee"} <= names and r["servings"] == 4
    for url in ["https://www.youtube.com/watch?v=7AuCVt-QrMQ", "https://youtu.be/7AuCVt-QrMQ?t=3",
                "https://youtube.com/shorts/7AuCVt-QrMQ", "7AuCVt-QrMQ"]:
        assert video_id(url) == "7AuCVt-QrMQ"
    assert video_id("https://example.com") is None
    assert normalize("𝟮 𝘁𝘀𝗽 ½") == "2 tsp ½"
