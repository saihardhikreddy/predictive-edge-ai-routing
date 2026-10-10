#!/usr/bin/env bash
# Runs the real APK on an Android emulator: launch, enter a name, restart, check the name
# card stays away, start the mesh, and look for crashes. Screenshots go to emu/.
set -u
PKG=edu.amrita.team8.meshtestbed
ACT=com.bitchat.android.MainActivity
OUT=emu
mkdir -p "$OUT"
fail=0
note() { echo "::notice title=Emulator::$1"; }
err() { echo "::error title=Emulator::$1"; fail=1; }
shot() { adb exec-out screencap -p > "$OUT/$1.png"; }
# tap the centre of the first UI node whose text/hint/content-desc contains $1
tap_text() {
  adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1
  adb pull /sdcard/ui.xml "$OUT/ui.xml" >/dev/null 2>&1
  xy=$(python3 - "$1" "$OUT/ui.xml" <<'PY'
import re, sys, xml.etree.ElementTree as ET
want, path = sys.argv[1].lower(), sys.argv[2]
try:
    root = ET.parse(path).getroot()
except Exception:
    sys.exit(0)
for n in root.iter("node"):
    hay = " ".join(n.get(k, "") for k in ("text", "hint", "content-desc")).lower()
    if want in hay:
        x1, y1, x2, y2 = map(int, re.findall(r"\d+", n.get("bounds", "")))
        print((x1 + x2) // 2, (y1 + y2) // 2)
        break
PY
)
  if [ -n "$xy" ]; then adb shell input tap $xy; return 0; fi
  return 1
}
ui_has() { adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1; adb pull /sdcard/ui.xml "$OUT/ui.xml" >/dev/null 2>&1; grep -qi "$1" "$OUT/ui.xml"; }

adb install -r apk/app-debug.apk || err "install failed"
for p in BLUETOOTH_SCAN BLUETOOTH_CONNECT BLUETOOTH_ADVERTISE; do adb shell pm grant $PKG android.permission.$p 2>/dev/null; done
adb logcat -c

# 1. first launch: the name card must appear
adb shell am start -W -n $PKG/$ACT >/dev/null
sleep 30
shot 1_first_launch
pid=$(adb shell pidof $PKG | tr -d '\r')
if [ -n "$pid" ]; then note "app is running after first launch"; else err "app is not running after launch"; fi
if ui_has "What should your friends see"; then note "first launch asks for a name"; else err "first launch did not show the name card"; fi

# 2. enter a name
tap_text "your name" || err "could not find the name field"
sleep 1
adb shell input text "Hardhik"
sleep 1
tap_text "save name" || adb shell input keyevent 66
sleep 4
shot 2_after_name
prefs=$(adb shell run-as $PKG cat shared_prefs/mesh.xml 2>/dev/null | tr -d '\r')
if echo "$prefs" | grep -q "Hardhik"; then note "name saved to storage"; else err "name not saved: $prefs"; fi

# 3. close and reopen: the name card must NOT come back
adb shell am force-stop $PKG
sleep 2
adb shell am start -W -n $PKG/$ACT >/dev/null
sleep 25
shot 3_after_restart
if ui_has "What should your friends see"; then err "name card shown again after restart"; else note "name remembered after restart (no name card)"; fi
if ui_has "Hardhik"; then note "top pill shows the saved name"; else err "saved name not shown after restart"; fi

# 4. start the mesh and visit each chapter
tap_text "start" || err "could not find Start"
sleep 6
shot 4_started
for ch in Send Route Defend Lab Mesh; do
  tap_text "$ch" && sleep 4 && shot "5_${ch}"
done

# 5. crashes and page errors
adb logcat -d > "$OUT/logcat.txt"
if grep -q "FATAL EXCEPTION" "$OUT/logcat.txt"; then
  err "app crashed: $(grep -A8 'FATAL EXCEPTION' "$OUT/logcat.txt" | head -12 | tr '\n' ' ')"
else
  note "no crashes in logcat"
fi
if grep -i "chromium" "$OUT/logcat.txt" | grep -qi "Uncaught"; then
  err "JavaScript error: $(grep -i chromium "$OUT/logcat.txt" | grep -i Uncaught | head -3 | tr '\n' ' ')"
else
  note "no JavaScript errors in the 3D UI"
fi
pid=$(adb shell pidof $PKG | tr -d '\r')
if [ -n "$pid" ]; then note "app still running at the end"; else err "app died during the test"; fi
exit $fail
