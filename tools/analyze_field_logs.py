#!/usr/bin/env python3
"""Merge the CSV logs exported from every phone and compute field-test metrics.

Usage:
    python tools/analyze_field_logs.py field_logs/*.csv
    python tools/analyze_field_logs.py field_logs/ --since 2026-10-10T14:00 --until 2026-10-10T14:30

Prints a Markdown summary per routing mode:
  - messages originated / delivered (a message counts once, whichever copy arrived)
  - packet delivery ratio (PDR), SOS PDR
  - delivery-confirmation RTT measured on the *source* phone (no clock sync needed)
  - hops, data frames and all frames (incl. ACKs/HELLOs) per delivered message, bytes on air
  - per-phone battery drop over the window
  - sinkhole: packets swallowed, who quarantined whom and how long after sinkhole mode was switched on
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import statistics as st
from collections import defaultdict
from datetime import datetime


def load(paths):
    rows = []
    for p in paths:
        files = glob.glob(os.path.join(p, "*.csv")) if os.path.isdir(p) else [p]
        for f in files:
            with open(f, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    try:
                        r["ts"] = int(r["ts_ms"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    for k in ("node", "event", "mode", "msg", "src", "dst", "peer", "rssi", "hops", "bytes", "value", "battery"):
                        r[k] = r.get(k) or ""
                    rows.append(r)
    # the same phone's log may be exported twice: dedupe exact rows
    seen, out = set(), []
    for r in rows:
        k = (r["ts_ms"], r["node"], r["event"], r["msg"], r["peer"], r["value"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return sorted(out, key=lambda r: r["ts"])


def parse_time(s):
    return int(datetime.fromisoformat(s).timestamp() * 1000) if s else None


def fmt(xs, unit=""):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "–"
    m = st.mean(xs)
    return f"{m:.1f}{unit}" + (f" (median {st.median(xs):.1f}{unit})" if len(xs) > 2 else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--since")
    ap.add_argument("--until")
    a = ap.parse_args()
    rows = load(a.paths)
    lo, hi = parse_time(a.since), parse_time(a.until)
    rows = [r for r in rows if (lo is None or r["ts"] >= lo) and (hi is None or r["ts"] <= hi)]
    if not rows:
        print("No rows in range.")
        return

    nodes = sorted({r["node"] for r in rows})
    nick = {}
    for r in rows:
        if r["event"] == "START" and r["value"].startswith("nick="):
            nick[r["node"]] = r["value"][5:]

    orig = {}  # msg -> row
    for r in rows:
        if r["event"] == "ORIG":
            orig[r["msg"]] = r
    msg_mode = {m: r["mode"] for m, r in orig.items()}
    delivered = {}  # msg -> first DELIVER row
    for r in rows:
        if r["event"] == "DELIVER" and r["msg"] in orig and r["msg"] not in delivered:
            delivered[r["msg"]] = r
    rtt = {}
    for r in rows:
        if r["event"] == "DELACK_RX" and r["msg"] not in rtt:
            try:
                rtt[r["msg"]] = int(r["value"])
            except ValueError:
                pass

    frames = defaultdict(lambda: {"data": 0, "all": 0, "bytes": 0, "fail": 0})
    hello = {"all": 0, "bytes": 0}
    for r in rows:
        if r["event"] not in ("TX_OK", "TX_FAIL"):
            continue
        b = int(r["bytes"]) if r["bytes"].isdigit() else 0
        if r["value"] == "Hello":
            hello["all"] += 1
            hello["bytes"] += b
            continue
        mode = r["mode"] or msg_mode.get(r["msg"], "?")
        f = frames[mode]
        f["all"] += 1
        f["bytes"] += b
        if r["value"] == "Data":
            f["data"] += 1
        if r["event"] == "TX_FAIL":
            f["fail"] += 1

    print(f"# Field test summary\n\nPhones: {', '.join(nick.get(n, n) + f' ({n})' for n in nodes)}")
    t0, t1 = rows[0]["ts"], rows[-1]["ts"]
    print(f"Window: {datetime.fromtimestamp(t0 / 1000):%Y-%m-%d %H:%M:%S} → {datetime.fromtimestamp(t1 / 1000):%H:%M:%S} ({(t1 - t0) / 60000:.1f} min)\n")

    print("| Mode | Sent | Delivered | PDR | SOS PDR | RTT at source (ms) | Hops | Data frames / delivered | All frames / delivered | Bytes / delivered | Failed writes |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for mode, label in (("M", "MARL"), ("F", "Flooding")):
        ms = [m for m, md in msg_mode.items() if md == mode]
        if not ms:
            continue
        d = [m for m in ms if m in delivered]
        sos = [m for m in ms if orig[m]["value"].startswith("EMERGENCY_SOS")]
        sos_d = [m for m in sos if m in delivered]
        f = frames[mode]
        nd = max(1, len(d))
        hops = [int(delivered[m]["hops"]) for m in d if delivered[m]["hops"].isdigit()]
        print(f"| {label} | {len(ms)} | {len(d)} | {len(d) / len(ms):.0%} | "
              f"{(f'{len(sos_d) / len(sos):.0%}' if sos else '–')} | {fmt([rtt.get(m) for m in ms])} | {fmt(hops)} | "
              f"{f['data'] / nd:.1f} | {f['all'] / nd:.1f} | {f['bytes'] / nd:.0f} | {f['fail']} |")
    print(f"\nHELLO/encounter traffic (shared by both modes): {hello['all']} frames, {hello['bytes']} bytes.")

    print("\n## Battery\n")
    for n in nodes:
        bs = [int(r["battery"]) for r in rows if r["node"] == n and r["battery"].isdigit()]
        if bs:
            print(f"- {nick.get(n, n)}: {bs[0]}% → {bs[-1]}% (Δ {bs[0] - bs[-1]} pts)")

    sink_on = {r["node"]: r["ts"] for r in rows if r["event"] == "SINKHOLE_MODE" and r["value"] == "true"}
    drops = [r for r in rows if r["event"] == "SINK_DROP"]
    quar = [r for r in rows if r["event"] == "QUARANTINE"]
    if sink_on or drops or quar:
        print("\n## Sinkhole\n")
        for n, ts in sink_on.items():
            print(f"- {nick.get(n, n)} switched sinkhole mode on at {datetime.fromtimestamp(ts / 1000):%H:%M:%S}")
        print(f"- Packets swallowed: {len(drops)}")
        for q in quar:
            target = q["peer"]
            dt = (q["ts"] - sink_on[target]) / 1000 if target in sink_on else None
            kind = "true positive" if target in sink_on else "FALSE POSITIVE"
            when = f", {dt:.0f}s after the attack started" if dt is not None else ""
            print(f"- {nick.get(q['node'], q['node'])} quarantined {nick.get(target, target)} ({kind}{when})")

    fl = [r for r in rows if r["event"] == "FL_MERGE"]
    print(f"\nFederated averaging rounds: {len(fl)}")


if __name__ == "__main__":
    main()
