"""Tadka backend.

Phone (React Native)  --JPEG frames over WS /ws/camera-->  this server
this server  --state @ 4 Hz + events over WS /ws/dashboard-->  React 3D dashboard
                                     MJPEG /api/stream.mjpg -->  live annotated camera view
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import socket
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .classifier import Classifier, load_classifier
from .config import DATA_DIR, WEB_DIST, settings
from .demo import run_demo
from .dishes import load_catalog
from .markers import SpoonTracker, marker_png
from .pantry import Pantry
from .video_recipe import fetch_recipe, list_recipes, load_recipe, save_recipe, video_id
from .pipeline import FrameAnalysis, Pipeline
from .storage import Storage
from .tracker import Burner, Session, Tracker
from .vision import ClarityMonitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("tadka")

ZONES_FILE = DATA_DIR / "zones.json"
DEFAULT_BURNERS = [
    {"id": "b1", "name": "Back left", "zone": {"x": 0.06, "y": 0.08, "w": 0.4, "h": 0.4}},
    {"id": "b2", "name": "Back right", "zone": {"x": 0.54, "y": 0.08, "w": 0.4, "h": 0.4}},
    {"id": "b3", "name": "Front left", "zone": {"x": 0.06, "y": 0.52, "w": 0.4, "h": 0.4}},
    {"id": "b4", "name": "Front right", "zone": {"x": 0.54, "y": 0.52, "w": 0.4, "h": 0.4}},
]


class AppState:
    def __init__(self) -> None:
        self.catalog = load_catalog()
        self.pantry = Pantry()
        self.tracker = Tracker(self.catalog, unattended_minutes=settings.unattended_minutes,
                               session_gap_seconds=settings.session_gap_seconds, pantry=self.pantry)
        self.spoons = SpoonTracker(
            {i.marker: i.id for i in self.pantry.ingredients.values() if i.marker is not None},
            {s.marker: s.id for s in self.pantry.spoons.values() if s.marker is not None})
        self.marker_names = {**{i.marker: i.name for i in self.pantry.ingredients.values() if i.marker is not None},
                             **{s.marker: s.name for s in self.pantry.spoons.values() if s.marker is not None}}
        self.storage = Storage(DATA_DIR / "history.sqlite3")
        self.pipeline = Pipeline(settings.frame_max_width)
        self.clarity = ClarityMonitor()
        self.classifier: Classifier = Classifier()
        self.classifier.ready = settings.classifier == "mock"
        self.classifier_loading = settings.classifier != "mock"
        self.dashboards: set[WebSocket] = set()
        self.cameras: dict[WebSocket, dict] = {}
        self.latest_jpeg: tuple[bytes, float] | None = None
        self.latest_analysis: FrameAnalysis | None = None
        self.preview: bytes | None = None
        self.preview_version = 0
        self.frame_event = asyncio.Event()
        self.frames_in = 0
        self.fps = 0.0
        self.last_frame_at: float | None = None
        self.last_classify = 0.0
        self.classifying = False
        self.demo_stop: asyncio.Event | None = None
        self.tasks: list[asyncio.Task] = []


state: AppState  # created in lifespan


# --------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------
def lan_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the LAN interface
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def info() -> dict:
    ip = lan_ip()
    return {
        "lan_ip": ip,
        "port": settings.port,
        "camera_ws": f"ws://{ip}:{settings.port}/ws/camera",
        "dashboard_url": f"http://{ip}:{settings.port}",
        "classifier": {**state.classifier.info(), "loading": state.classifier_loading},
        "demo": state.demo_stop is not None,
    }


def camera_status(now: float) -> dict:
    connected = bool(state.cameras)
    fresh = state.last_frame_at is not None and now - state.last_frame_at < 5
    return {
        "connected": connected,
        "streaming": fresh,
        "fps": round(state.fps, 2) if fresh else 0,
        "last_frame_at": state.last_frame_at,
        "devices": [c.get("device", "phone") for c in state.cameras.values()],
        "fogged": state.clarity.fogged and fresh,
        "phone": next((c.get("status") for c in state.cameras.values() if c.get("status")), None),
        "clarity": round(min(1.0, state.clarity.ratio), 2),
    }


def full_state() -> dict:
    now = time.time()
    return {"type": "state", "ts": now, "burners": state.tracker.snapshot(now), "camera": camera_status(now),
            "demo": state.demo_stop is not None,
            "profile": state.pantry.profile.__dict__,
            "classifier": {**state.classifier.info(), "loading": state.classifier_loading}}


async def broadcast(msg: dict) -> None:
    if not state.dashboards:
        return
    text = json.dumps(msg)
    dead = []
    for ws in list(state.dashboards):
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        state.dashboards.discard(ws)


def save_zones() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ZONES_FILE.write_text(json.dumps(state.tracker.burner_specs(), indent=2))


def load_zones() -> list[dict]:
    if ZONES_FILE.exists():
        with suppress(Exception):
            return json.loads(ZONES_FILE.read_text())
    return DEFAULT_BURNERS


def on_session_end(b: Burner, s: Session, now: float) -> None:
    if s.demo or state.demo_stop is not None:
        return
    t = state.tracker
    state.storage.save({
        "burner_id": b.id, "burner_name": b.name, "dish_id": t.dish_id(s), "dish": t.dish_name(s),
        "confidence": t.dish_confidence(s), "overridden": int(bool(s.override_dish or s.override_label)),
        "started_at": s.started_at, "ended_at": now, "cook_seconds": s.cook_seconds,
        "target_seconds": t.target_seconds(s), "stirs": s.stirs,
        "alerts": ",".join(sorted(a for a in s.fired if ":" not in a)),
        "ingredients": json.dumps(t._ingredient_rows(s)) if s.ingredients else None,
        "profile": state.pantry.profile.name,
    })


# --------------------------------------------------------------------------------------------
# background loops
# --------------------------------------------------------------------------------------------
async def broadcast_loop() -> None:
    period = 1.0 / settings.broadcast_hz
    while True:
        state.tracker.tick()
        await broadcast(full_state())
        await asyncio.sleep(period)


async def classify(analysis: FrameAnalysis) -> None:
    state.classifying = True
    try:
        ids = list(analysis.crops)
        crops = [analysis.crops[i] for i in ids]
        results = await asyncio.to_thread(state.classifier.classify, crops)
        if results:
            for bid, probs in zip(ids, results):
                state.tracker.observe_probs(bid, probs)
        # Learn from the user's corrections while they're active.
        for bid in ids:
            b = state.tracker.burners.get(bid)
            if b and b.session and b.session.override_dish and b.flame_on:
                await asyncio.to_thread(state.classifier.learn, b.session.override_dish, analysis.crops[bid])
    except Exception:
        log.exception("classification failed")
    finally:
        state.classifying = False


async def frame_loop() -> None:
    window: list[float] = []
    while True:
        await state.frame_event.wait()
        state.frame_event.clear()
        if state.latest_jpeg is None:
            continue
        jpeg, ts = state.latest_jpeg
        zones = [(b.id, b.zone, b.baseline_blue) for b in state.tracker.burners.values()]
        try:
            analysis = await asyncio.to_thread(state.pipeline.analyze, jpeg, zones)
        except Exception:
            log.exception("frame analysis failed")
            continue
        if analysis is None:
            continue
        now = time.time()
        window = [t for t in window if now - t < 5] + [now]
        state.fps = len(window) / 5.0
        state.last_frame_at = now
        state.latest_analysis = analysis
        change = state.clarity.update(analysis.sharpness, now)
        if change is True:
            state.tracker.emit(None, "fog", "Camera lens looks fogged — wipe it. Timers are holding their "
                               "last flame state until it clears.", "warn")
        elif change is False and state.clarity.expired:
            state.tracker.emit(None, "fog_clear", "Camera still looks blurry after a minute — tracking again; "
                               "check the lens if timers look wrong", "warn")
        elif change is False:
            state.tracker.emit(None, "fog_clear", "Camera view is clear again", "success")
        if state.clarity.fogged:
            # Don't trust blurry frames: keep flame states as they were, skip dish + spoon detection.
            state.preview = await asyncio.to_thread(state.pipeline.render, analysis.frame, state.tracker.snapshot(now))
            state.preview_version += 1
            continue
        if state.demo_stop is None:
            for o in analysis.obs:
                state.tracker.observe_signals(o.burner_id, o.flame, o.motion, now)
            zones = [(b.id, b.zone) for b in state.tracker.burners.values()]
            for ev in state.spoons.update(analysis.markers, zones, now):
                b = state.tracker.burners.get(ev.burner_id)
                if ev.ingredient is None:
                    if b and b.session:
                        state.tracker.emit(b, "unknown_spoon", f"A {state.pantry.spoons[ev.spoon].name.lower()} "
                                           f"went into {b.name} — which spice? Tap it on the card.", "warn")
                    continue
                with suppress(LookupError):
                    log_spoonful(ev.burner_id, ev.ingredient, ev.spoon, 1.0, source="camera")
        if (state.classifier.ready and not state.classifying
                and now - state.last_classify >= settings.classify_interval):
            state.last_classify = now
            asyncio.create_task(classify(analysis))
        state.preview = await asyncio.to_thread(state.pipeline.render, analysis.frame,
                                                state.tracker.snapshot(now), analysis.markers,
                                                state.marker_names)
        state.preview_version += 1


async def load_classifier_bg() -> None:
    try:
        clf = await asyncio.to_thread(load_classifier, settings.classifier, state.catalog,
                                      settings.clip_model, settings.clip_pretrained)
        state.classifier = clf
    except Exception:
        log.exception("could not load classifier, continuing without dish recognition")
        state.classifier = Classifier()
    finally:
        state.classifier_loading = False
        state.classifier.ready = True
        await broadcast({"type": "info", "info": info()})


def log_spoonful(bid: str, ingredient: str, spoon: str, count: float, source: str) -> dict:
    p = state.pantry
    grams = p.grams(ingredient, spoon, count)
    unit = p.spoons[spoon]
    label = f"{count:g} {unit.id if unit.id in ('tsp', 'tbsp') else unit.name.lower()}"
    return state.tracker.add_ingredient(bid, ingredient, grams, source=source, amount_label=label)


def start_demo() -> None:
    if state.demo_stop is not None:
        return
    for bid in list(state.tracker.burners):
        state.tracker.reset(bid)
    state.demo_stop = asyncio.Event()
    state.tasks.append(asyncio.create_task(run_demo(state.tracker, state.demo_stop)))
    state.tracker.emit(None, "demo", "Demo mode on — simulated stove", "info")


def stop_demo() -> None:
    if state.demo_stop is None:
        return
    state.demo_stop.set()
    for bid in list(state.tracker.burners):
        state.tracker.reset(bid)
        state.tracker.burners[bid].flame_auto = False
        state.tracker.burners[bid].probs = {}
    state.demo_stop = None
    state.tracker.emit(None, "demo", "Demo mode off", "info")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global state
    state = AppState()
    state.tracker.set_burners(load_zones())
    state.tracker.session_listeners.append(on_session_end)
    loop = asyncio.get_running_loop()
    state.tracker.event_listeners.append(  # thread-safe: events can come from any thread
        lambda ev: loop.call_soon_threadsafe(lambda: loop.create_task(broadcast({"type": "event", "event": ev}))))
    state.tasks += [asyncio.create_task(broadcast_loop()), asyncio.create_task(frame_loop())]
    if settings.classifier != "mock":
        state.tasks.append(asyncio.create_task(load_classifier_bg()))
    if settings.demo:
        start_demo()
    ip = lan_ip()
    log.info("Dashboard: http://localhost:%s  (dev: http://localhost:5173)", settings.port)
    log.info("Phone camera WebSocket: ws://%s:%s/ws/camera", ip, settings.port)
    yield
    if state.demo_stop:
        state.demo_stop.set()
    for t in state.tasks:
        t.cancel()


app = FastAPI(title="Tadka — cooking monitor", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# --------------------------------------------------------------------------------------------
# REST
# --------------------------------------------------------------------------------------------
class ZoneIn(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class BurnerIn(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=40)
    zone: ZoneIn


class OverrideIn(BaseModel):
    dish_id: str | None = None
    label: str | None = Field(default=None, max_length=60)
    target_minutes: float | None = Field(default=None, gt=0, le=600)
    batch: float | None = Field(default=None, gt=0, le=10)


class FlameIn(BaseModel):
    on: bool | None


class IngredientIn(BaseModel):
    ingredient: str
    spoon: str | None = None          # spoon id (tsp / tbsp / ladle / pinch) …
    count: float = Field(default=1, gt=0, le=50)
    grams: float | None = Field(default=None, gt=0, le=5000)   # … or exact grams (e.g. from a scale)


class ProfileIn(BaseModel):
    id: str = Field(min_length=1, max_length=32, pattern="^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=40)
    emoji: str = Field(default="🙂", max_length=8)
    multipliers: dict[str, float] = Field(default_factory=dict)
    tolerance: float = Field(default=0.15, ge=0, le=1)
    fill: float = Field(default=1.0, gt=0, le=3)


class ProfilesIn(BaseModel):
    profiles: list[ProfileIn] = Field(min_length=1, max_length=12)
    active: str | None = None


class ActiveIn(BaseModel):
    id: str


class CameraCommandIn(BaseModel):
    cmd: str = Field(pattern="^(pause|resume|fps|torch|buzz)$")
    value: float | bool | None = None


class VideoIn(BaseModel):
    url: str = Field(min_length=5, max_length=300)


class VideoItemIn(BaseModel):
    ingredient: str | None = None
    name: str = Field(max_length=60)
    grams: float | None = Field(default=None, ge=0, le=20000)
    to_taste: bool = False
    time: float | None = None
    source: str = "edited"
    lines: list[str] = Field(default_factory=list)


class VideoEditIn(BaseModel):
    title: str | None = None
    servings: int | None = Field(default=None, ge=1, le=100)
    items: list[VideoItemIn] = Field(max_length=60)


class FollowIn(BaseModel):
    video_id: str
    scale: float = Field(default=1.0, gt=0, le=20)


class RatingIn(BaseModel):
    profile_id: str | None = None
    ratings: dict[str, str]          # {"salty": "too much" | "right" | "too little", "heat": ...}


class DismissIn(BaseModel):
    alert: str = Field(pattern="^(empty_flame|unattended|target)$")


class DemoIn(BaseModel):
    enabled: bool


def _burner(bid: str) -> Burner:
    b = state.tracker.burners.get(bid)
    if b is None:
        raise HTTPException(404, f"unknown burner {bid}")
    return b


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/info")
async def get_info() -> dict:
    return info()


@app.get("/api/state")
async def get_state() -> dict:
    return {**full_state(), "events": list(state.tracker.events)[-40:]}


@app.get("/api/dishes")
def get_dishes() -> list[dict]:
    return [d.public() for d in state.catalog.dishes]


@app.get("/api/zones")
def get_zones() -> list[dict]:
    return state.tracker.burner_specs()


@app.put("/api/zones")
async def put_zones(burners: list[BurnerIn]) -> list[dict]:
    if not 1 <= len(burners) <= 8 or len({b.id for b in burners}) != len(burners):
        raise HTTPException(400, "need 1-8 burners with unique ids")
    old = {b["id"]: b for b in state.tracker.burner_specs()}
    specs = [{**b.model_dump(), "baseline_blue": old.get(b.id, {}).get("baseline_blue", 0.0)} for b in burners]
    state.tracker.set_burners(specs)
    save_zones()
    return state.tracker.burner_specs()


@app.post("/api/calibrate/baseline")
async def calibrate_baseline() -> dict:
    """Call with every burner OFF: records each zone's static blue level (blue pans, tiles…)."""
    a = state.latest_analysis
    if a is None:
        raise HTTPException(409, "no camera frame yet")
    for o in a.obs:
        if o.burner_id in state.tracker.burners:
            state.tracker.burners[o.burner_id].baseline_blue = o.blue
    save_zones()
    state.tracker.emit(None, "calibrate", "Flame baseline captured", "success")
    return {"baselines": {o.burner_id: o.blue for o in a.obs}}


@app.post("/api/burners/{bid}/override")
async def override(bid: str, body: OverrideIn) -> dict:
    _burner(bid)
    if body.dish_id and not state.catalog.get(body.dish_id):
        raise HTTPException(400, "unknown dish")
    state.tracker.set_override(bid, body.dish_id, body.label, body.target_minutes, body.batch)
    return {"ok": True}


@app.post("/api/burners/{bid}/flame")
async def manual_flame(bid: str, body: FlameIn) -> dict:
    _burner(bid)
    state.tracker.set_manual_flame(bid, body.on)
    return {"ok": True}


@app.post("/api/camera/command")
async def camera_command(body: CameraCommandIn) -> dict:
    """Remote-control the phone (handy when its screen is broken or it's mounted out of reach)."""
    msg = json.dumps({"type": "command", "cmd": body.cmd, "value": body.value})
    sent = 0
    for ws in list(state.cameras):
        try:
            await ws.send_text(msg)
            sent += 1
        except Exception:
            pass
    if not sent:
        raise HTTPException(409, "no phone connected")
    return {"sent": sent}


@app.post("/api/video/parse")
async def parse_video(body: VideoIn) -> dict:
    """Read a recipe from a YouTube link (title, description, captions; no video download)."""
    if not video_id(body.url):
        raise HTTPException(400, "That doesn't look like a YouTube link")
    try:
        return await asyncio.to_thread(fetch_recipe, body.url, state.pantry)
    except Exception as e:
        log.exception("video fetch failed")
        raise HTTPException(502, f"Couldn't read that video: {str(e)[:160]}")


@app.get("/api/videos")
def videos() -> list[dict]:
    return list_recipes()


@app.get("/api/video/{vid}")
def get_video(vid: str) -> dict:
    r = load_recipe(vid)
    if r is None:
        raise HTTPException(404, "unknown video")
    return r


@app.put("/api/video/{vid}")
async def edit_video(vid: str, body: VideoEditIn) -> dict:
    r = load_recipe(vid)
    if r is None:
        raise HTTPException(404, "unknown video")
    for it in body.items:
        if it.ingredient and it.ingredient not in state.pantry.ingredients:
            raise HTTPException(400, f"unknown ingredient {it.ingredient}")
    r["items"] = [it.model_dump() for it in body.items]
    if body.title:
        r["title"] = body.title
    r["servings"] = body.servings
    r["edited"] = True
    save_recipe(r)
    return r


@app.post("/api/burners/{bid}/follow")
async def follow(bid: str, body: FollowIn) -> dict:
    _burner(bid)
    r = load_recipe(body.video_id)
    if r is None:
        raise HTTPException(404, "read the video first")
    state.tracker.set_follow(bid, r, body.scale)
    return {"ok": True}


@app.delete("/api/burners/{bid}/follow")
async def unfollow(bid: str) -> dict:
    _burner(bid)
    state.tracker.set_follow(bid, None)
    return {"ok": True}


@app.get("/api/pantry")
def get_pantry() -> dict:
    return state.pantry.public()


@app.put("/api/profiles")
async def put_profiles(body: ProfilesIn) -> dict:
    ids = [p.id for p in body.profiles]
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "profile ids must be unique")
    state.pantry.save_profiles([p.model_dump() for p in body.profiles], body.active)
    return state.pantry.public()


@app.post("/api/profiles/active")
async def set_profile(body: ActiveIn) -> dict:
    try:
        state.pantry.set_active(body.id)
    except KeyError:
        raise HTTPException(404, "unknown profile")
    p = state.pantry.profile
    state.tracker.emit(None, "profile", f"Cooking for {p.emoji} {p.name}", "info")
    return {"active": body.id}


@app.post("/api/burners/{bid}/ingredient")
async def add_ingredient(bid: str, body: IngredientIn) -> dict:
    _burner(bid)
    if body.ingredient not in state.pantry.ingredients:
        raise HTTPException(400, "unknown ingredient")
    try:
        if body.grams is not None:
            return state.tracker.add_ingredient(bid, body.ingredient, body.grams, amount_label=f"{body.grams:g} g")
        if body.spoon not in state.pantry.spoons:
            raise HTTPException(400, "give a known spoon or grams")
        return log_spoonful(bid, body.ingredient, body.spoon, body.count, source="manual")
    except LookupError as e:
        raise HTTPException(409, str(e))


@app.post("/api/burners/{bid}/ingredient/undo")
async def undo_ingredient(bid: str) -> dict:
    _burner(bid)
    return {"undone": state.tracker.undo_ingredient(bid)}


@app.get("/api/markers/{marker_id}.png")
def get_marker(marker_id: int) -> Response:
    if not 0 <= marker_id < 50:
        raise HTTPException(404)
    return Response(marker_png(marker_id), media_type="image/png", headers={"Cache-Control": "max-age=86400"})


@app.post("/api/burners/{bid}/dismiss")
async def dismiss(bid: str, body: DismissIn) -> dict:
    _burner(bid)
    state.tracker.dismiss(bid, body.alert)
    return {"ok": True}


@app.post("/api/burners/{bid}/reset")
async def reset(bid: str) -> dict:
    _burner(bid)
    state.tracker.reset(bid)
    return {"ok": True}


@app.post("/api/demo")
async def demo(body: DemoIn) -> dict:
    start_demo() if body.enabled else stop_demo()
    return {"demo": state.demo_stop is not None}


@app.get("/api/history")
def history(limit: int = 50) -> dict:
    return {"sessions": state.storage.history(min(limit, 500)), "stats": state.storage.stats()}


@app.post("/api/history/{sid}/rate")
async def rate(sid: int, body: RatingIn) -> dict:
    """'How did it taste?' — adjusts the profile so next time's targets fit this person better."""
    pid = body.profile_id or state.pantry.active_profile
    if pid not in state.pantry.profiles:
        raise HTTPException(404, "unknown profile")
    ok = {"too much", "right", "too little"}
    if not body.ratings or any(v not in ok for v in body.ratings.values()):
        raise HTTPException(400, "ratings must be 'too much', 'right' or 'too little'")
    state.storage.save_rating(sid, pid, body.ratings)
    mult = state.pantry.learn_from_rating(pid, body.ratings)
    p = state.pantry.profiles[pid]
    state.tracker.emit(None, "learned", f"Noted for {p.emoji} {p.name}: " + ", ".join(f"{k} {v}" for k, v in body.ratings.items()))
    return {"profile": pid, "multipliers": mult}


@app.get("/api/frame.jpg")
def frame() -> Response:
    if state.preview is None:
        raise HTTPException(404, "no frame yet")
    return Response(state.preview, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/stream.mjpg")
async def stream(request: Request) -> StreamingResponse:
    async def gen():
        seen = -1
        while not await request.is_disconnected():
            if state.preview is not None and state.preview_version != seen:
                seen = state.preview_version
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                       + str(len(state.preview)).encode() + b"\r\n\r\n" + state.preview + b"\r\n")
            await asyncio.sleep(0.05)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


# --------------------------------------------------------------------------------------------
# WebSockets
# --------------------------------------------------------------------------------------------
@app.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket) -> None:
    await ws.accept()
    state.dashboards.add(ws)
    try:
        await ws.send_text(json.dumps({"type": "hello", "info": info(), "dishes": get_dishes(),
                                       "pantry": state.pantry.public(),
                                       "events": list(state.tracker.events)[-40:], "state": full_state()}))
        while True:
            await ws.receive_text()  # dashboard → server commands go over REST; keep-alive only
    except WebSocketDisconnect:
        pass
    finally:
        state.dashboards.discard(ws)


def phone_summary() -> dict:
    out = []
    for b in state.tracker.snapshot():
        s = b["session"]
        out.append({"id": b["id"], "name": b["name"], "status": b["status"], "flame": b["flame"]["on"],
                    "zone": b["zone"], "dish": s["dish"] if s else None,
                    "seconds": s["cook_seconds"] if s else 0, "progress": s["progress"] if s else None})
    last = list(state.tracker.events)[-1:] if state.tracker.events else []
    p = state.pantry
    return {"type": "summary", "burners": out, "fps": round(state.fps, 2), "last_event": last[0] if last else None,
            "fogged": state.clarity.fogged,
            "profile": {"id": p.profile.id, "name": p.profile.name, "emoji": p.profile.emoji},
            "profiles": [{"id": x.id, "name": x.name, "emoji": x.emoji} for x in p.profiles.values()]}


@app.websocket("/ws/camera")
async def ws_camera(ws: WebSocket) -> None:
    """Phone sends JPEG frames: either binary messages, or JSON {"type":"frame","jpeg":"<base64>"}."""
    await ws.accept()
    meta = {"device": "phone", "connected_at": time.time()}
    state.cameras[ws] = meta
    state.tracker.emit(None, "camera", "Phone camera connected", "success")
    last_summary = 0.0
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            jpeg: bytes | None = msg.get("bytes")
            if jpeg is None and msg.get("text"):
                data = json.loads(msg["text"])
                if data.get("type") == "status":
                    st = {k: data.get(k) for k in ("battery", "charging", "paused", "fps", "torch")}
                    meta["status"] = st
                    low = st["battery"] is not None and st["battery"] <= 20 and st["charging"] is False
                    if low and not meta.get("low_warned"):
                        meta["low_warned"] = True
                        state.tracker.emit(None, "battery", f"Camera phone battery at {st['battery']}% — plug it in",
                                           "warn")
                    elif not low:
                        meta["low_warned"] = False
                    continue
                if data.get("type") == "hello":
                    meta["device"] = str(data.get("device", "phone"))[:60]
                    await ws.send_text(json.dumps({"type": "welcome", "info": info()}))
                    continue
                if data.get("type") == "frame" and data.get("jpeg"):
                    b64 = data["jpeg"]
                    if b64.startswith("data:"):
                        b64 = b64.split(",", 1)[1]
                    jpeg = base64.b64decode(b64)
            if jpeg:
                state.frames_in += 1
                state.latest_jpeg = (jpeg, time.time())
                state.frame_event.set()
                now = time.time()
                if now - last_summary >= 1.0:
                    last_summary = now
                    await ws.send_text(json.dumps(phone_summary()))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        state.cameras.pop(ws, None)
        state.tracker.emit(None, "camera", "Phone camera disconnected", "warn")


# --------------------------------------------------------------------------------------------
# Serve the built React dashboard (npm run build in ../web) from the same port.
# --------------------------------------------------------------------------------------------
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (WEB_DIST / path).resolve()
        if path and candidate.is_file() and WEB_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
