import cv2
import numpy as np

from app.markers import MarkerDetector, SpoonTracker
from app.pantry import Pantry
from app.vision import Zone
from tests.test_tracker import Clock, dal_probs, run
from app.dishes import load_catalog
from app.tracker import Tracker


def make():
    clock = Clock()
    pantry = Pantry()
    pantry.profiles = {"me": pantry.profiles["me"], "mild": pantry.profiles["mild"]}
    pantry.active_profile = "me"
    t = Tracker(load_catalog(), clock=clock, pantry=pantry)
    t.set_burners([{"id": "b1", "name": "Front", "zone": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}}])
    run(t, clock, 5, flame=0.9, probs=dal_probs())  # dal is cooking
    return t, clock, pantry


def test_grams_from_spoons():
    p = Pantry()
    p.active_profile = "me"
    assert p.grams("salt", "tsp") == 6.0          # 5 ml × 1.2 g/ml
    assert p.grams("sugar", "tbsp") == 12.75
    assert p.grams("salt", "tsp", fill=1.5) == 9.0  # heaped


def test_too_much_salt_beeps_and_profile_changes_the_limit():
    t, c, pantry = make()
    events = []
    t.event_listeners.append(events.append)
    r = t.add_ingredient("b1", "salt", 6.0, amount_label="1 tsp")
    assert r["target"] == 8 and r["state"] == "under"
    assert any(e["kind"] == "careful" for e in events)          # another tsp would overshoot
    r = t.add_ingredient("b1", "salt", 6.0, amount_label="1 tsp")
    assert r["state"] == "over"
    assert any(e["kind"] == "too_much" and e["level"] == "danger" and "salt" in e["message"] for e in events)

    # Same 6 g of salt for the "mild" profile (0.7×) is already right; 12 g is way over.
    pantry.active_profile = "mild"
    rows = {r["id"]: r for r in t.snapshot()[0]["session"]["ingredients"]}
    assert rows["salt"]["target"] == 5.6 and rows["salt"]["state"] == "over"
    assert rows["chili"]["target"] == 1.0 and rows["chili"]["grams"] == 0


def test_spot_on_and_undo():
    t, c, _ = make()
    events = []
    t.event_listeners.append(events.append)
    t.add_ingredient("b1", "salt", 7.5)
    assert any(e["kind"] == "ingredient_ok" for e in events)
    t.undo_ingredient("b1")
    assert t.burners["b1"].session.ingredients["salt"] == 0


def test_forgot_salt_reminder():
    t, c, _ = make()
    events = []
    t.event_listeners.append(events.append)
    t.add_ingredient("b1", "turmeric", 1.5)
    t.burners["b1"].session.cook_seconds = 13 * 60   # past half of dal's 25 min
    run(t, c, 1, flame=0.9)
    assert any(e["kind"] == "forgot" and "salt" in e["message"] for e in events)


def test_no_session_refuses():
    clock = Clock()
    t = Tracker(load_catalog(), clock=clock, pantry=Pantry())
    t.set_burners([{"id": "b1", "name": "Front", "zone": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}}])
    try:
        t.add_ingredient("b1", "salt", 6)
        assert False
    except LookupError:
        pass


def _frame(markers):
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    img = np.full((480, 640, 3), 200, np.uint8)
    for mid, (x, y) in markers.items():
        m = cv2.cvtColor(cv2.aruco.generateImageMarker(d, mid, 48), cv2.COLOR_GRAY2BGR)
        img[y:y + 48, x:x + 48] = m
    return img


def test_spoon_marker_scoop_then_pot_counts_one_spoonful():
    det = MarkerDetector()
    pot = [("b1", Zone(0.5, 0.3, 0.4, 0.5))]
    st = SpoonTracker({1: "salt", 2: "sugar"}, {40: "tsp"})
    # salt + sugar boxes on the counter (left), spoon next to the salt box
    f1 = _frame({1: (20, 20), 2: (20, 300), 40: (90, 30)})
    assert st.update(det.detect(f1), pot, 0.0) == []
    # spoon over the pot
    f2 = _frame({1: (20, 20), 2: (20, 300), 40: (450, 250)})
    ev = st.update(det.detect(f2), pot, 1.0)
    assert [(e.burner_id, e.ingredient, e.spoon) for e in ev] == [("b1", "salt", "tsp")]
    # hovering over the pot again without re-scooping doesn't double count
    assert st.update(det.detect(f2), pot, 2.0) == []


def test_salt_sugar_mixup_is_caught():
    t, c, _ = make()                       # dal: salt in the recipe, no sugar
    events = []
    t.event_listeners.append(events.append)
    r = t.add_ingredient("b1", "sugar", 4.25, amount_label="1 tsp")
    assert r["state"] == "mixup"
    assert any(e["kind"] == "mixup" and "did you mean salt" in e["message"] for e in events)
