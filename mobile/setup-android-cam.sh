#!/usr/bin/env bash
# One-time setup: turn an Android phone (cracked screen is fine) into Sous Chef AI's stove camera,
# driving it from the Mac over USB. Tested flow for Motorola / stock-ish Android 12+.
#
#   ./setup-android-cam.sh             # USB cable
#   ./setup-android-cam.sh --wireless  # afterwards, switch adb + mirroring to Wi-Fi (cable can go)
#
# Before running, on the phone (once): Settings > About phone > tap "Build number" 7 times,
# then Settings > System > Developer options > turn on "USB debugging".
set -euo pipefail
cd "$(dirname "$0")"

EXPO_GO=host.exp.exponent
METRO_PORT=8081

say()  { printf "\n\033[1;33m▶ %s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
die()  { printf "\n\033[31m✗ %s\033[0m\n" "$*"; exit 1; }
need() { command -v "$1" >/dev/null || die "$1 not found — run: brew install --cask android-platform-tools && brew install scrcpy"; }
need adb
need scrcpy

mac_ip() { ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo ""; }

# --------------------------------------------------------------------------------------------
say "Looking for the phone"
case "$(adb get-state 2>&1 || true)" in
  device) ok "connected: $(adb shell getprop ro.product.manufacturer | tr -d '\r') $(adb shell getprop ro.product.model | tr -d '\r'), Android $(adb shell getprop ro.build.version.release | tr -d '\r')" ;;
  *unauthorized*)
    die "The phone is asking 'Allow USB debugging?'. Unlock it and tap Allow (tick 'Always allow').
   Touch broken but screen visible? Plug a USB mouse into the phone with a USB-C OTG adapter and click it." ;;
  *)
    die "No phone found. Either:
   • USB: cable supports data (not charge-only), phone unlocked, USB debugging on
     (Settings > System > Developer options), USB mode set to 'File transfer'; or
   • Wi-Fi (no cable; best when the phone's only port is used by a mouse):
     Developer options > Wireless debugging > Pair device with pairing code, then on the Mac:
       adb pair <ip>:<pairing-port> <6-digit-code>
       adb connect <ip>:<port shown on the Wireless debugging screen>" ;;
esac

# --------------------------------------------------------------------------------------------
say "Wi-Fi"
PHONE_IP=$(adb shell ip -f inet addr show wlan0 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | tr -d '\r')
MAC_IP=$(mac_ip)
if [[ -z "$PHONE_IP" ]]; then
  echo "  The phone isn't on Wi-Fi. Opening its Wi-Fi settings in a mirror window: pick your network"
  echo "  and type the password yourself with the Mac keyboard, then close the window and re-run this script."
  adb shell am start -a android.settings.WIFI_SETTINGS >/dev/null
  scrcpy --window-title "Phone: connect to Wi-Fi" >/dev/null 2>&1 || true
  exit 1
fi
ok "phone $PHONE_IP, Mac ${MAC_IP:-unknown}"
[[ -n "$MAC_IP" && "${PHONE_IP%.*}" != "${MAC_IP%.*}" ]] && echo "  ⚠ Different subnets: the phone may not find the Mac. Use the same Wi-Fi network."

# --------------------------------------------------------------------------------------------
say "Expo Go (runs the Sous Chef Cam app)"
if ! adb shell pm list packages "$EXPO_GO" | grep -q "$EXPO_GO"; then
  echo "  Opening Expo Go in the Play Store on the phone, mirrored here: click Install with your mouse."
  adb shell am start -a android.intent.action.VIEW -d "market://details?id=$EXPO_GO" >/dev/null
  scrcpy --window-title "Phone: install Expo Go, then close this window" >/dev/null 2>&1 &
  SCRCPY=$!
  for _ in $(seq 1 120); do
    adb shell pm list packages "$EXPO_GO" | grep -q "$EXPO_GO" && break
    sleep 5
  done
  kill $SCRCPY 2>/dev/null || true
  adb shell pm list packages "$EXPO_GO" | grep -q "$EXPO_GO" || die "Expo Go didn't get installed."
fi
ok "Expo Go installed"

adb shell pm grant "$EXPO_GO" android.permission.CAMERA && ok "camera permission granted (no tap needed)"
adb shell dumpsys deviceidle whitelist "+$EXPO_GO" >/dev/null && ok "excluded from battery optimisation (Android won't kill it)"
adb shell svc power stayon true && ok "screen stays on while powered (the app also keeps itself awake)"

# --------------------------------------------------------------------------------------------
say "Opening Sous Chef Cam on the phone"
if ! curl -s "http://localhost:$METRO_PORT/status" | grep -q running; then
  echo "  Starting the app server (npx expo start) in the background…"
  (CI=1 npx expo start --lan --port "$METRO_PORT" >/tmp/souschef-expo.log 2>&1 &)
  for _ in $(seq 1 60); do curl -s "http://localhost:$METRO_PORT/status" | grep -q running && break; sleep 2; done
fi
curl -s "http://localhost:$METRO_PORT/status" | grep -q running || die "Expo dev server didn't start; see /tmp/souschef-expo.log"
adb shell am start -a android.intent.action.VIEW -d "exp://$MAC_IP:$METRO_PORT" "$EXPO_GO" >/dev/null
ok "launched. It finds the Sous Chef AI server by itself and starts streaming."
echo "  (Keep 'cd backend && .venv/bin/python -m app' running on the Mac.)"

# --------------------------------------------------------------------------------------------
if [[ "${1:-}" == "--wireless" ]]; then
  say "Switching to Wi-Fi control (you can unplug the cable)"
  adb tcpip 5555 >/dev/null && sleep 2
  adb connect "$PHONE_IP:5555"
  ok "connected wirelessly. Mirror/control any time with:  scrcpy -s $PHONE_IP:5555 --turn-screen-off"
  echo "  (Wireless adb resets if the phone reboots; plug in and re-run with --wireless.)"
fi

say "Done. To see and control the phone from the Mac (its own screen stays off, less heat):"
echo "  scrcpy --turn-screen-off"
