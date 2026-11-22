import numpy as np
import cv2

from app.dishes import EMPTY, LID, load_catalog
from app.tracker import Tracker
from app.vision import blue_fraction, flame_score


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def make(unattended=8.0, gap=60.0):
    clock = Clock()
    t = Tracker(load_catalog(), unattended_minutes=unattended, session_gap_seconds=gap, clock=clock)
    t.set_burners([{"id": "b1", "name": "Front", "zone": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}}])
    return t, clock


def run(t, clock, seconds, flame, motion=0.01, probs=None, step=0.5):
    for _ in range(int(seconds / step)):
        clock.t += step
        t.observe_signals("b1", flame, motion)
        if probs:
            t.observe_probs("b1", probs)
        t.tick()


def dal_probs():
    p = {k: 0.01 for k in load_catalog().dish_ids}
    p["dal"] = 0.8
    p[EMPTY] = 0.01
    return p


def test_flame_hysteresis_starts_and_times_session():
    t, c = make()
    run(t, c, 1.0, flame=0.9)
    assert t.burners["b1"].session is None  # needs FLAME_ON_HOLD
    run(t, c, 10.0, flame=0.9)
    s = t.burners["b1"].session
    assert s is not None
    assert 8.0 <= s.cook_seconds <= 10.0
    # a brief dip (pot hides the flame) doesn't stop the timer
    run(t, c, 2.0, flame=0.0)
    assert t.burners["b1"].flame_on


def test_dish_identified_and_target_alert():
    t, c = make()
    events = []
    t.event_listeners.append(events.append)
    run(t, c, 5, flame=0.9, probs=dal_probs())
    snap = t.snapshot()[0]
    assert snap["session"]["dish"] == "Dal"
    assert snap["session"]["target_seconds"] == 25 * 60
    t.burners["b1"].session.cook_seconds = 25 * 60 - 1
    run(t, c, 2, flame=0.9)
    assert any(e["kind"] == "target" for e in events)
    assert t.snapshot()[0]["status"] == "overdue"


def test_lid_keeps_previous_guess():
    t, c = make()
    run(t, c, 5, flame=0.9, probs=dal_probs())
    lid = {k: 0.0 for k in load_catalog().dish_ids}
    lid["rice"] = 0.3
    lid[LID] = 0.7
    run(t, c, 20, flame=0.9, probs=lid)
    assert t.snapshot()[0]["session"]["dish"] == "Dal"


def test_override_wins_and_survives_until_session():
    t, c = make()
    t.set_override("b1", None, "Nani's kheer", 30)
    run(t, c, 5, flame=0.9, probs=dal_probs())
    s = t.snapshot()[0]["session"]
    assert s["dish"] == "Nani's kheer"
    assert s["target_seconds"] == 1800


def test_unattended_and_stir_reset():
    t, c = make(unattended=1.0)
    events = []
    t.event_listeners.append(events.append)
    run(t, c, 70, flame=0.9)
    assert [e for e in events if e["kind"] == "unattended"]
    run(t, c, 1, flame=0.9, motion=0.2)  # a stir
    assert t.burners["b1"].session.stirs >= 1
    assert "unattended" not in t.burners["b1"].session.fired


def test_empty_burner_with_flame_is_danger():
    t, c = make()
    events = []
    t.event_listeners.append(events.append)
    empty = {EMPTY: 0.9, "dal": 0.1}
    run(t, c, 20, flame=0.9, probs=empty)
    assert not any(e["kind"] == "empty_flame" for e in events)  # needs sustained evidence
    run(t, c, 40, flame=0.9, probs=empty)
    assert any(e["kind"] == "empty_flame" and e["level"] == "danger" for e in events)
    assert t.snapshot()[0]["status"] == "danger"
    # user says there's a pot: alert clears and stays quiet for this session
    t.dismiss("b1", "empty_flame")
    run(t, c, 60, flame=0.9, probs=empty)
    assert t.snapshot()[0]["status"] == "cooking"
    assert sum(e["kind"] == "empty_flame" for e in events) == 1


def test_session_ends_after_gap_and_is_reported():
    t, c = make(gap=30)
    ended = []
    t.session_listeners.append(lambda b, s, now: ended.append(s))
    run(t, c, 40, flame=0.9, probs=dal_probs())
    run(t, c, 45, flame=0.0)
    assert t.burners["b1"].session is None
    assert len(ended) == 1 and ended[0].cook_seconds > 30


def test_blue_flame_detection_on_synthetic_image():
    img = np.zeros((100, 100, 3), np.uint8)
    img[:] = (40, 40, 40)
    assert flame_score(blue_fraction(img), 0.0) == 0.0
    cv2.circle(img, (50, 50), 30, (255, 120, 30), 3)  # BGR bright blue ring
    assert flame_score(blue_fraction(img), 0.0) == 1.0
