from fastapi.testclient import TestClient

from app.dishes import load_catalog
from app.pantry import Pantry
from app.tracker import Tracker
from app.video_recipe import save_recipe
from tests.test_tracker import Clock, run

COOKIES = {
    "id": "f-M3JN_7LGU", "title": "Chocolate chip cookies", "url": "https://youtu.be/f-M3JN_7LGU",
    "items": [
        {"ingredient": "butter", "name": "Butter", "grams": 114, "to_taste": False, "time": 49},
        {"ingredient": "sugar", "name": "Sugar", "grams": 100, "to_taste": False, "time": 106},
        {"ingredient": "salt", "name": "Salt", "grams": 3, "to_taste": False, "time": 143},
        {"ingredient": None, "name": "Chopped walnuts", "grams": 60, "to_taste": False, "time": None},
    ],
}


def make():
    clock = Clock()
    pantry = Pantry()
    pantry.active_profile = "me"
    t = Tracker(load_catalog(), clock=clock, pantry=pantry)
    t.set_burners([{"id": "b1", "name": "Front", "zone": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}}])
    return t, clock, pantry


def test_follow_before_lighting_then_beep_when_over_the_video():
    t, c, p = make()
    events = []
    t.event_listeners.append(events.append)
    t.set_follow("b1", COOKIES, scale=0.5)          # half batch, set before the flame is on
    run(t, c, 5, flame=0.9)
    f = t.snapshot()[0]["session"]["follow"]
    assert f["next"]["ingredient"] == "butter"      # first thing the video adds
    targets = {r["id"]: r["target"] for r in t.snapshot()[0]["session"]["ingredients"]}
    assert targets["sugar"] == 50 and targets["butter"] == 57
    walnut = next(s for s in f["steps"] if s["name"] == "Chopped walnuts")
    assert walnut["ingredient"].startswith("x_") and walnut["ingredient"] in p.ingredients  # loggable

    t.add_ingredient("b1", "butter", 57)
    assert t.snapshot()[0]["session"]["follow"]["next"]["ingredient"] == "sugar"
    t.add_ingredient("b1", "sugar", 75)             # 75 g vs 50 g in a half batch of the video
    msg = next(e for e in events if e["kind"] == "too_much")["message"]
    assert "the video uses 50 g" in msg


def test_profile_still_applies_on_top_of_the_video():
    t, c, p = make()
    p.profiles["me"].multipliers["sugar"] = 0.5     # this person likes it less sweet
    t.set_follow("b1", COOKIES)
    run(t, c, 5, flame=0.9)
    targets = {r["id"]: r["target"] for r in t.snapshot()[0]["session"]["ingredients"]}
    assert targets["sugar"] == 50 and targets["butter"] == 114


def test_follow_api_round_trip():
    from app.main import app
    save_recipe(dict(COOKIES))
    with TestClient(app) as client:
        client.put("/api/zones", json=[{"id": "b1", "name": "Front", "zone": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}}])
        assert client.post("/api/video/parse", json={"url": "https://example.com/x"}).status_code == 400
        assert client.get("/api/video/f-M3JN_7LGU").json()["title"].startswith("Chocolate")
        edited = client.put("/api/video/f-M3JN_7LGU", json={"items": COOKIES["items"][:2]}).json()
        assert len(edited["items"]) == 2 and edited["edited"]
        assert client.post("/api/burners/b1/follow", json={"video_id": "f-M3JN_7LGU", "scale": 2}).json()["ok"]
        client.post("/api/burners/b1/flame", json={"on": True})
        import time
        time.sleep(0.6)
        b1 = next(b for b in client.get("/api/state").json()["burners"] if b["id"] == "b1")
        assert b1["session"]["follow"]["scale"] == 2
        r = client.post("/api/burners/b1/ingredient", json={"ingredient": "sugar", "grams": 250}).json()
        assert r["target"] == 200 and r["state"] == "over"
        assert client.delete("/api/burners/b1/follow").json()["ok"]
