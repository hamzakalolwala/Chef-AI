import time

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app


def jpeg(flame: bool) -> bytes:
    img = np.full((480, 640, 3), 35, np.uint8)
    if flame:  # blue ring inside the default "Back left" zone
        cv2.circle(img, (165, 135), 60, (255, 130, 30), 6)
    return cv2.imencode(".jpg", img)[1].tobytes()


def test_camera_frames_light_a_burner():
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"ok": True}
        assert len(client.get("/api/dishes").json()) > 10
        with client.websocket_connect("/ws/camera") as cam:
            cam.send_json({"type": "hello", "device": "pytest"})
            assert cam.receive_json()["type"] == "welcome"
            for _ in range(12):
                cam.send_bytes(jpeg(True))
                time.sleep(0.25)
        burners = {b["id"]: b for b in client.get("/api/state").json()["burners"]}
        assert burners["b1"]["flame"]["on"] is True
        assert burners["b1"]["session"] is not None
        assert burners["b4"]["flame"]["on"] is False
        assert client.get("/api/frame.jpg").headers["content-type"] == "image/jpeg"


def test_override_manual_flame_and_zones():
    with TestClient(app) as client:
        assert client.post("/api/burners/b2/override", json={"dish_id": "chai", "target_minutes": 6}).json()["ok"]
        client.post("/api/burners/b2/flame", json={"on": True})
        time.sleep(0.6)
        b2 = next(b for b in client.get("/api/state").json()["burners"] if b["id"] == "b2")
        assert b2["session"]["dish"] == "Chai" and b2["session"]["target_seconds"] == 360
        zones = [{"id": "x1", "name": "Big", "zone": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}}]
        assert client.put("/api/zones", json=zones).status_code == 200
        assert [b["id"] for b in client.get("/api/zones").json()] == ["x1"]
        assert client.post("/api/burners/b2/reset").status_code == 404


def test_dashboard_ws_and_demo():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/dashboard") as ws:
            assert ws.receive_json()["type"] == "hello"
            client.post("/api/demo", json={"enabled": True})
            msg = ws.receive_json()
            while msg["type"] != "state":
                msg = ws.receive_json()
            assert msg["demo"] is True
        client.post("/api/demo", json={"enabled": False})


def test_phone_status_and_remote_commands():
    with TestClient(app) as client:
        assert client.post("/api/camera/command", json={"cmd": "pause"}).status_code == 409  # no phone yet
        with client.websocket_connect("/ws/camera") as cam:
            cam.send_json({"type": "status", "battery": 15, "charging": False, "paused": False, "fps": 2, "torch": False})
            time.sleep(0.3)
            st = client.get("/api/state").json()
            assert st["camera"]["phone"]["battery"] == 15
            assert any(e["kind"] == "battery" for e in st["events"])
            assert client.post("/api/camera/command", json={"cmd": "fps", "value": 3}).json() == {"sent": 1}
            assert cam.receive_json() == {"type": "command", "cmd": "fps", "value": 3}
            assert client.post("/api/camera/command", json={"cmd": "explode"}).status_code == 422
