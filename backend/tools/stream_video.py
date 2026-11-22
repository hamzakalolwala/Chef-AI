"""Stream a video file (or the Mac's webcam) to the backend exactly like the phone app does.

    python tools/stream_video.py my_cooking.mp4
    python tools/stream_video.py 0            # webcam index
    python tools/stream_video.py clip.mp4 --fps 2 --url ws://localhost:8000/ws/camera

Handy for tuning zones / flame thresholds on a recording without standing at the stove.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

import cv2
import websockets


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="video path or webcam index")
    ap.add_argument("--url", default="ws://localhost:8000/ws/camera")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--loop", action="store_true", help="restart the video when it ends")
    args = ap.parse_args()

    src = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {args.source}")
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    skip = max(1, int(round(video_fps / args.fps))) if isinstance(src, str) else 1

    async with websockets.connect(args.url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "device": f"stream_video:{args.source}"}))
        sent = 0
        while True:
            t0 = time.time()
            frame = None
            for _ in range(skip):
                ok, frame = cap.read()
                if not ok:
                    frame = None
                    break
            if frame is None:
                if args.loop and isinstance(src, str):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                break
            h, w = frame.shape[:2]
            if w > args.width:
                frame = cv2.resize(frame, (args.width, int(h * args.width / w)))
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            await ws.send(buf.tobytes())
            sent += 1
            try:
                while True:  # drain summaries without blocking
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.001))
                    if msg.get("type") == "summary":
                        line = "  ".join(f"{b['name']}: {b['dish'] or '-'} {int(b['seconds'])}s"
                                         + (" 🔥" if b["flame"] else "") for b in msg["burners"])
                        print(f"\r[{sent}] {line}", end="", flush=True)
            except (asyncio.TimeoutError, TimeoutError):
                pass
            await asyncio.sleep(max(0.0, 1.0 / args.fps - (time.time() - t0)))
    print("\ndone")


if __name__ == "__main__":
    asyncio.run(main())
