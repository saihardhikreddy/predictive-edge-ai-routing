#!/usr/bin/env python3
"""Evaluate JavaScript inside the app's WebView through Chrome DevTools.

    python3 ci/webview.py '<js expression>'      -> prints the JSON result

Needs `adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>` first
(ci/emulator-smoke.sh does that). Debug builds enable WebView debugging.
"""
import json
import sys
import time
import urllib.request

import websocket  # pip install websocket-client


def page_ws():
    for _ in range(20):
        try:
            pages = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=3))
            for p in pages:
                if p.get("type") == "page" and "index.html" in p.get("url", ""):
                    return p["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(1)
    raise SystemExit("no WebView page found over DevTools")


def evaluate(expr: str):
    ws = websocket.create_connection(page_ws(), timeout=10, suppress_origin=True)
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True, "awaitPromise": True}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == 1:
            ws.close()
            res = msg.get("result", {})
            if "exceptionDetails" in res:
                raise SystemExit("JS exception: " + json.dumps(res["exceptionDetails"])[:500])
            return res.get("result", {}).get("value")


if __name__ == "__main__":
    print(json.dumps(evaluate(sys.argv[1])))
