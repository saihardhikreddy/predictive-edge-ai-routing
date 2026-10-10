#!/usr/bin/env bash
# Runs the real APK on an Android emulator and drives the 3D page through Chrome DevTools:
# first-launch name card, saving a name, restart (name must be remembered), Start, every
# chapter, and crash / JavaScript-error checks. Screenshots go to emu/.
set -u
PKG=edu.amrita.team8.meshtestbed
ACT=com.bitchat.android.MainActivity
OUT=emu
mkdir -p "$OUT"
pip install -q websocket-client >/dev/null 2>&1 || pip install -q --break-system-packages websocket-client >/dev/null 2>&1
fail=0
note() { echo "::notice title=Emulator::$1"; }
err() { echo "::error title=Emulator::$1"; fail=1; }
shot() { adb exec-out screencap -p > "$OUT/$1.png"; }
js() { python3 ci/webview.py "$1" 2>&1; }
attach() {
  pid=""
  for _ in $(seq 1 20); do pid=$(adb shell pidof $PKG | tr -d '\r'); [ -n "$pid" ] && break; sleep 1; done
  [ -n "$pid" ] || { err "app is not running"; return 1; }
  adb forward --remove-all >/dev/null 2>&1
  adb forward tcp:9222 localabstract:webview_devtools_remote_$pid >/dev/null
  for _ in $(seq 1 30); do [ "$(js 'document.body.classList.contains("ready")')" = "true" ] && return 0; sleep 1; done
  err "3D page did not finish loading"; return 1
}
launch() { adb shell am start -W -n $PKG/$ACT >/dev/null; sleep 8; attach; }

adb install -r apk/app-debug.apk || err "install failed"
for p in BLUETOOTH_SCAN BLUETOOTH_CONNECT BLUETOOTH_ADVERTISE; do adb shell pm grant $PKG android.permission.$p 2>/dev/null; done
adb logcat -c

# 1. first launch must ask for a name
launch
sleep 3
shot 1_first_launch
v=$(js '!document.getElementById("namecard").hidden')
[ "$v" = "true" ] && note "first launch asks for a name" || err "first launch did not show the name card ($v)"

# 2. type a name and save, the way a user would
js 'const i=document.getElementById("nc-input"); i.focus(); i.value="Hardhik"; document.querySelector("#nc-form button[type=submit]").click(); "ok"' >/dev/null
sleep 3
shot 2_after_name
v=$(js 'document.getElementById("namecard").hidden && document.getElementById("pill-name").textContent')
[ "$v" = '"Hardhik"' ] && note "name card closed and the top shows Hardhik" || err "after saving, top shows $v"
prefs=$(adb shell run-as $PKG cat shared_prefs/mesh.xml 2>/dev/null | tr -d '\r')
echo "$prefs" | grep -q "Hardhik" && note "name saved to storage" || err "name not in storage: $prefs"

# 3. close the app completely and open it again: the name card must stay away
adb shell am force-stop $PKG
sleep 2
launch
sleep 4
shot 3_after_restart
v=$(js 'JSON.stringify({card: !document.getElementById("namecard").hidden, name: document.getElementById("pill-name").textContent})')
echo "after restart: $v"
echo "$v" | grep -q '\\"card\\":false' && note "name remembered after restart (no name card)" || err "name card came back after restart: $v"
echo "$v" | grep -q 'Hardhik' && note "top shows the saved name after restart" || err "saved name missing after restart: $v"

# 4. press Start
js 'document.getElementById("power").click(); "ok"' >/dev/null
sleep 8
shot 4_after_start
v=$(js 'document.getElementById("pill-sub").textContent + " | button: " + document.getElementById("power").textContent')
note "after pressing Start the top says: $v"

# 5. every chapter
for ch in send route defend lab mesh; do
  js "document.querySelector('.nav button[data-goto=$ch]').click(); 'ok'" >/dev/null
  sleep 4
  shot "5_$ch"
  v=$(js "document.body.dataset.chapter")
  [ "$v" = "\"$ch\"" ] || err "chapter $ch did not open ($v)"
done
note "visited all five chapters"

# 6. errors and crashes
v=$(js 'JSON.stringify(window.__errors || [])')
[ "$v" = '"[]"' ] && note "no JavaScript errors in the page" || err "JavaScript errors: $v"
adb logcat -d > "$OUT/logcat.txt"
if grep -A3 "FATAL EXCEPTION" "$OUT/logcat.txt" | grep -q "Process: $PKG"; then
  err "app crashed: $(grep -A10 'FATAL EXCEPTION' "$OUT/logcat.txt" | grep -A8 "Process: $PKG" | head -10 | tr '\n' ' ')"
else
  note "no app crashes in logcat"
fi
[ -n "$(adb shell pidof $PKG | tr -d '\r')" ] && note "app still running at the end" || err "app died during the test"
exit $fail
