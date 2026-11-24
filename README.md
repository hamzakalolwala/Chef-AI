# Sous Chef AI — kitchen vision

Prop your phone over the gas stove. Sous Chef AI watches each burner, works out **what's cooking**,
times **how long each dish has been on the flame**, and shows it all as a live 3D stove on your
MacBook, with voice alerts when something's done, unattended, or lit with nothing on it.

```
 ┌──────────────┐  JPEG frames (WebSocket)   ┌────────────────────────────┐   state @4 Hz + events   ┌─────────────────────┐
 │  Phone        │ ─────────────────────────▶ │  Python backend (Mac)       │ ───────────────────────▶ │  React + three.js    │
 │  Expo / RN    │ ◀───────────────────────── │  FastAPI · OpenCV · CLIP    │   MJPEG live view        │  3D dashboard        │
 │"Sous Chef Cam"│   per-burner summary       │  tracker · SQLite history   │ ◀─────── REST ─────────── │  (browser on Mac)    │
 └──────────────┘                            └────────────────────────────┘                           └─────────────────────┘
```

## Quick start

```bash
cd Chef-AI
./dev.sh --demo        # first run creates the venv + installs everything; --demo needs no phone
```

Open <http://localhost:5173>. Leave out `--demo` to use the real camera.

**Phone app**

```bash
cd mobile && npm install && npx expo start
```

Scan the Expo QR with **Expo Go** (SDK 58) on your phone. In Sous Chef Cam tap **Scan dashboard QR**
and scan the code under **Connect phone** on the dashboard. Phone and Mac must be on the same Wi-Fi.
If macOS asks whether Python may accept incoming connections, click Allow.

**First-time calibration** (dashboard → *Camera & zones*)

1. Drag a box over each burner in the live view, then **Save zones**.
2. With every burner **off**, click **Capture flame baseline**. This teaches it which blue things
   (pans, tiles) are not flames.

## Ingredients, spoons & taste profiles

Sous Chef AI beeps and says **"Too much salt!"** when what goes into a pot passes what the person you're
cooking for likes.

- **Labels** (dashboard → *Labels* → Print): each sticker has the name for you (SALT, SUGAR…)
  and a square code for the camera. Stick them on box lids (facing up) and on spoon handles.
- **Spoonful = spoon touches a box, then goes over a pot.** Grams = spoon ml × ingredient density
  × how full that cook's spoons usually are. Spoons are measured once (`data/pantry.json`) instead
  of guessed from the pan's size: from above, a level and a heaped spoon look the same.
- **Manual quick-add** on each burner card (+pinch, +½ tsp, +1 tsp, +1 tbsp, undo) for anything
  the camera misses.
- **Targets** = recipe grams (`data/pantry.json`, per standard ~4-serving batch) × batch size ×
  profile multiplier. Alerts: *careful* (one more spoon would overshoot), *too much* (over by more than
  the profile's tolerance), *spot on*, and *no salt yet?* at half-time.
- **Profiles** (top bar → *Profiles*): per person, × salt / sugar / chili / … , beep tolerance, and
  whether their spoons are level or heaped. Switch "cooking for" from the dashboard or the phone.

For best spoon detection, stream at 3 fps while adding spices: a quick scoop can fall between frames.

## Mounting the camera (steam, heat, grease)

Don't mount the phone straight above a pot: that's the hottest, wettest spot.

- **Angle it from the front/side**, about 45° above the stove (cabinet edge, wall shelf, side wall). Steam rises
  straight up, so the lens stays out of the plume. Zones work on any angle, since you draw them on the camera view.
- **Turn the chimney / exhaust fan on.** It pulls the steam column away from the lens.
- **Shield the lens, not the phone.** A clear phone case or a small acrylic window in front of the lens,
  treated with anti-fog spray (glasses / swimming-goggle spray), is cheap and easy to wipe.
- **Keep it cool.** Phones throttle or shut off when hot; keep it plugged in, out of direct heat.
- **Or use a spare camera**: an old phone, or any Wi-Fi camera with an RTSP stream
  (`python tools/stream_video.py rtsp://<camera-ip>/stream`), so your main phone isn't in the kitchen.

**Hands-free phone (e.g. an old phone with a broken screen).** After the first setup, the app needs no taps:
on launch it reconnects to the last Mac or scans the Wi-Fi to find it, starts streaming, and dims its
screen after 20 s. From the dashboard (*Camera & zones → Phone remote*) you can pause/resume, change fps,
turn on the torch, or buzz the phone, and the top bar shows its battery. It warns when the battery drops
to 20% or less while unplugged.

**Android spare phone, set up from the Mac.** Turn on USB debugging once, plug in, then run
`mobile/setup-android-cam.sh`. Over adb it grants the camera permission, exempts the app from
battery optimisation, installs and opens Expo Go via a mirrored window, and launches Sous Chef Cam.
`--wireless` switches to Wi-Fi control so the cable can go. `scrcpy --turn-screen-off` mirrors
and controls the phone with its own display off.

If the lens fogs anyway, Sous Chef AI notices: view sharpness is compared with this camera's normal
sharpness. After ~4 s below 35% it shows **"lens fogged — wipe it"** (dashboard + phone). Until it
clears it holds each burner's last flame state, so the timers keep going, and pauses dish recognition
and spoon counting. Brief steam puffs are ignored.

## Reference recipes, balance and cut size

**Sister's recipes** in the top bar. Upload a sheet of recipes you love (`templates/reference_recipes_template.xlsx`,
or any layout: one row per ingredient, one row per recipe, or a text column). From them Sous Chef AI learns:

- **Your sweet spot**: what the simulated tongue reports for each recipe (sweet, bitter, sour, salty, rich), per
  kind of dish (cake, cookie, dessert…).
- **Balance** (`balance.py`): each ingredient's job. Structure comes from flour, eggs and cocoa; tenderness from
  sugar, fat and leavening; moisture from milk, curd and egg water; drying from flour and starch. The ratios
  between these jobs that make *her* recipes work become your ranges, with general defaults until there are enough.
  Example: one extra cup of flour with the same 2 eggs is flagged "too dry / dense (cakey)".

**Adapt to our taste** (`adapt.py`): paste a Pinterest/WhatsApp recipe or pick a YouTube one. The main dry
ingredient stays fixed, and everything else moves *together* toward the sweet spot while staying inside the
balance ranges. For example, less sugar also nudges milk and butter up, so the cake stays soft. The result shows
every change, why it was made, and the new amounts in grams and cups.

**Cut size** (`cuts.py`): small pieces have far more surface per gram. They cook through sooner, lose the fresh
green aroma faster, brown more and pick up more oil. The advisor picks a size for a fresher or a more cooked taste
and the cooking time you plan.

Sheets you import are personal and stay out of git (`backend/data/reference/`).

## Recipe Lab and heat sources (LPG / induction)

Recipe Lab fixes an old recipe ("my chai has a bitter, dry aftertaste") or creates a new one for the
people you pick. It works for chai and dal tadka, on LPG or induction:

- `heat.py` simulates the pot. On LPG, about a quarter of the flame's heat wraps the pot's sides and the
  flame ring makes a hot spot. Induction puts about 85% of its power into the base only, pulses on/off
  below about 800 W, and needs a steel or iron pot. Oil heats faster on induction and overshoots more easily.
- `cookchem.py` handles extraction. Tea strength and caffeine come out fast; tannins come out slowly and keep
  rising with long boiling, and milk protein binds some of them. Ginger and cardamom have their own rates.
  Tadka spices release aroma as the oil heats and start burning (bitter) above about 190 °C.
- The tongue now has astringency and an aftertaste (taste 30 s after swallowing). Each sensation fades at
  its own rate, so sugar hides bitterness while sipping but the bitterness lingers after it.
- `recipe_lab.py` cooks hundreds of versions in simulation, tastes each with every chosen person's tongue
  and keeps the best. It returns the changes, steps with timings for your burner (flame words on LPG,
  levels and watts on induction), and how the same recipe does on your other burners.

Each burner has a type (Camera & zones). Induction shows no flame, so its timer starts when you tap **On**.

## Simulated tongue

`backend/app/tongue.py` models how a person tastes the dish, so Sous Chef AI can say who will like it:

1. **Chemistry**: grams become concentrations in the dish's water (salt and sugar in mM, capsaicin in µM,
   acids, glutamate, fat).
2. **Receptors**: each taste channel follows the Beidler/Hill dose-response curve. The channels are
   salty (ENaC), sweet (T1R2/T1R3), bitter (T2Rs), sour (OTOP1), umami (T1R1/T1R3), chili heat (TRPV1)
   and fat (CD36).
3. **Mixtures**: sugar and salt hide bitterness, umami boosts saltiness, and fat and sugar calm chili heat.
4. **Liking**: each person has a "bliss point" per taste. The worst taste dominates the overall score,
   as penalty analysis in sensory science finds.
5. **People differ**: receptor sensitivity varies. About 25% are bitter super-tasters and 25% non-tasters.
   Chili tolerance varies too.

Burner cards show the live taste bars and a predicted score for each family profile.
`tools/cook_sim.py` uses a 30-person virtual panel to score finished dishes. Parameters are approximate
literature values: it's a principled simulation, not a measurement.

## How it works

| Signal | How | Where |
|---|---|---|
| Flame on/off | bright saturated **blue** pixels in the burner zone, minus the calibrated baseline, with hysteresis (on after 1.5 s, off after 4 s, so a pot briefly hiding the flame doesn't stop the timer) | `backend/app/vision.py`, `tracker.py` |
| Dish | **OpenCLIP zero-shot**: each dish in `data/dishes.json` is a set of text prompts; each burner crop is scored every 2 s. Evidence is accumulated over the session, and a lid freezes the guess. | `classifier.py` |
| Learns your kitchen | when you correct a dish, crops are saved to `data/samples/<dish>/` and blended in as few-shot prototypes | `classifier.py` |
| Stirring / attention | motion bursts in the zone (camera shake subtracted) | `pipeline.py` |
| Steam | sustained low motion, drives the 3D steam | `tracker.py` |
| Timer | seconds the flame was **on** (not wall time); target from the dish's typical minutes or your override | `tracker.py` |
| Alerts | target reached · not stirred for 8 min · lit with nothing on it (40 s sustained, dismissable) | `tracker.py` |
| History | finished sessions (flame off for 3 min) go to SQLite, under **History** | `storage.py` |

No ML installed? It still works: flame timing, manual dish labels and alerts all run on plain
OpenCV. `pip install -r requirements-ml.txt` adds dish recognition (runs on the Mac's GPU via MPS).

## Layout

```
backend/   FastAPI app (python -m app), tests (pytest), tools/stream_video.py
web/       Vite + React 19 + @react-three/fiber dashboard
mobile/    Expo SDK 58 camera app
```

## Handy commands

```bash
cd backend && .venv/bin/python -m pytest -q                        # tests
cd backend && .venv/bin/python tools/stream_video.py clip.mp4 --loop  # replay a recording as if it were the phone
cd web && npm run build    # then the backend serves the dashboard itself at http://<mac-ip>:8000
```

Settings are environment variables: `SOUSCHEF_CLASSIFIER` (auto|clip|mock), `SOUSCHEF_CLASSIFY_INTERVAL`,
`SOUSCHEF_UNATTENDED_MIN`, `SOUSCHEF_SESSION_GAP`, `SOUSCHEF_DEMO=1`, `SOUSCHEF_PORT`. See `backend/app/config.py`.

## Known limits

- Dish recognition is zero-shot and has only been checked on synthetic frames, not a real stove yet.
  Expect to correct it at first; corrections are what make it learn.
- Flame detection assumes a blue gas flame. Induction or electric stoves need a different signal (heat/glow).
- Everything stays on your LAN; no frames leave the Mac.
