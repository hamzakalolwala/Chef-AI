import cv2
import numpy as np

from app.vision import ClarityMonitor, sharpness


def scene(seed=0):
    rng = np.random.default_rng(seed)
    img = np.full((480, 640, 3), 40, np.uint8)
    for _ in range(40):  # grates, pots, edges
        x, y, r = rng.integers(40, 600), rng.integers(40, 440), rng.integers(10, 60)
        cv2.circle(img, (int(x), int(y)), int(r), tuple(int(c) for c in rng.integers(60, 255, 3)), 3)
    return img


def fog(img):
    """Steam on the lens: heavy blur + washed-out contrast."""
    blurred = cv2.GaussianBlur(img, (0, 0), 9)
    return cv2.addWeighted(blurred, 0.5, np.full_like(img, 200), 0.5, 0)


def test_sharpness_drops_when_fogged():
    img = scene()
    assert sharpness(fog(img)) < 0.2 * sharpness(img)


def test_monitor_flags_fog_after_hold_and_clears():
    m, t = ClarityMonitor(), 0.0
    clear, foggy = sharpness(scene()), sharpness(fog(scene()))
    for _ in range(20):
        t += 0.5
        assert m.update(clear, t) is None
    changes = []
    for _ in range(12):  # 6 s of fog
        t += 0.5
        changes.append(m.update(foggy, t))
    assert True in changes and m.fogged
    assert changes.index(True) >= 7  # needed ~4 s, a single steam puff isn't enough
    for _ in range(6):
        t += 0.5
        m.update(clear, t)
    assert not m.fogged


def test_brief_steam_puff_is_ignored():
    m, t = ClarityMonitor(), 0.0
    clear, foggy = sharpness(scene()), sharpness(fog(scene()))
    for _ in range(20):
        t += 0.5
        m.update(clear, t)
    for v in [foggy, foggy, foggy, clear, clear]:
        t += 0.5
        m.update(v, t)
    assert not m.fogged


def test_fog_hold_is_capped_when_the_scene_just_changed():
    """After a pot is taken away the view is less detailed for good: don't hold timers forever."""
    m, t = ClarityMonitor(), 0.0
    busy, empty = sharpness(scene()), sharpness(fog(scene()))  # stands in for a much plainer view
    for _ in range(20):
        t += 0.5
        m.update(busy, t)
    changes = []
    for _ in range(200):  # 100 s of the plainer view
        t += 0.5
        changes.append(m.update(empty, t))
    assert True in changes and False in changes and m.expired and not m.fogged
    assert changes.index(False) - changes.index(True) <= 2 * m.MAX_FOG + 2
