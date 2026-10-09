#!/usr/bin/env python3
"""Headless benchmark: Flooding vs Predictive MARL (+ ablations), with seeds.

Usage:
    python benchmark.py               # full run (~2-4 min on a laptop)
    python benchmark.py --quick       # smoke run (~20 s)

Writes to results/:
    runs.csv            one row per (experiment, variant, nodes, seed)
    summary.md          mean +/- std tables to paste into the report/slides
    *.png               charts (needs matplotlib; skipped if missing)

Every variant with the same seed sees the *same* mobility trace and the
*same* message sequence (separate RNG streams), so differences come from the
protocol only.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import statistics as st
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, List

from simulation.mesh_engine import MeshSimulationEngine

VARIANTS = {
    # name: (protocol_mode, learning, federated, ids)
    "Flooding (BitChat TTL=7)": ("FLOODING", False, False, False),
    "MARL (full)": ("MARL", True, True, True),
    "MARL w/o learning (PRoPHET prior)": ("MARL", False, False, True),
    "MARL w/o federated gossip": ("MARL", True, False, True),
}
ORDER = list(VARIANTS)
VARIANTS["MARL (no IDS)"] = ("MARL", True, True, False)  # attack experiment only
COLD_VARIANTS = ["Cold start, no learning", "Cold start + TD learning", "Cold start + TD + gossip FL"]
VARIANTS["Cold start, no learning"] = ("MARL", False, False, True)
VARIANTS["Cold start + TD learning"] = ("MARL", True, False, True)
VARIANTS["Cold start + TD + gossip FL"] = ("MARL", True, True, True)
# validated default categorical palette (fixed order: blue, orange, aqua, yellow)
COLORS = {
    "MARL (full)": "#2a78d6",
    "Flooding (BitChat TTL=7)": "#eb6834",
    "MARL w/o learning (PRoPHET prior)": "#1baf7a",
    "MARL w/o federated gossip": "#eda100",
    "MARL (no IDS)": "#e87ba4",
    "Cold start, no learning": "#1baf7a",
    "Cold start + TD learning": "#eda100",
    "Cold start + TD + gossip FL": "#2a78d6",
}
MARKERS = {ORDER[0]: "s", ORDER[1]: "o", ORDER[2]: "^", ORDER[3]: "D"}


def one_run(job: Dict) -> Dict:
    mode, learn, fed, ids = VARIANTS[job["variant"]]
    e = MeshSimulationEngine(
        node_count=job["nodes"],
        seed=job["seed"],
        learning_enabled=learn,
        federated_enabled=fed,
        ids_enabled=ids,
        traffic_interval_s=job["traffic_interval"],
        cold_start=job.get("cold_start", False),
    )
    e.protocol_mode = mode
    dt = 0.1
    attack_at = job.get("attack_at")
    attacked = False
    gen_before = deliv_before = 0
    window = job.get("window")
    curve = []
    wg = wd = 0
    for step in range(int(job["duration"] / dt)):
        if window and step > 0 and step % int(window / dt) == 0:
            mm = e.m["marl"]
            curve.append((mm["delivered"] - wd) / max(1, mm["generated"] - wg))
            wg, wd = mm["generated"], mm["delivered"]
        if attack_at is not None and not attacked and e.sim_time >= attack_at:
            proto = "marl" if mode == "MARL" else "flood"
            gen_before, deliv_before = e.m[proto]["generated"], e.m[proto]["delivered"]
            e.inject_sinkhole()
            attacked = True
        e.tick(dt)
    s = e.summary()
    p = s["marl"] if mode == "MARL" else s["flood"]
    row = {
        "experiment": job["experiment"],
        "variant": job["variant"],
        "nodes": job["nodes"],
        "seed": job["seed"],
        "generated": p["generated"],
        "pdr": p["pdr"],
        "latency_s": p["latency_s"],
        "hops": p["hops"],
        "data_tx": p["data_tx"],
        "control_tx": p["control_tx"],
        "tx_per_delivery": p["tx_per_delivery"],
        "energy_per_delivery": p["energy_per_delivery"],
        "bytes_total": p["bytes_total"],
        "collisions_per_msg": p["collisions"] / p["generated"] if p["generated"] else 0.0,
        "sos_pdr": p["sos_pdr"],
        "sos_latency_s": p["sos_latency_s"],
        "sinkhole_drops": p["sinkhole_drops"],
        "ids_detection_s": s["ids"]["detection_s"],
        "false_positives": s["ids"]["false_positives"],
        "fl_rounds": s["fl_rounds"],
        "triage_raw_bytes": s["triage"]["avg_raw_bytes"],
        "triage_air_bytes": s["triage"]["avg_air_bytes"],
        "sos_raw_bytes": s["triage"]["sos_raw_bytes"],
        "sos_air_bytes": s["triage"]["sos_air_bytes"],
    }
    if window:
        mm = e.m["marl"]
        curve.append((mm["delivered"] - wd) / max(1, mm["generated"] - wg))
        for i, c in enumerate(curve):
            row[f"pdr_w{i:02d}"] = c
    if attacked:
        g = p["generated"] - gen_before
        d = p["delivered"] - deliv_before
        row["pdr_after_attack"] = d / g if g else float("nan")
    return row


def ms(xs: List[float]) -> str:
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if not xs:
        return "n/a"
    m = st.mean(xs)
    sd = st.stdev(xs) if len(xs) > 1 else 0.0
    if abs(m) >= 100:
        return f"{m:.0f} ± {sd:.0f}"
    return f"{m:.2f} ± {sd:.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    seeds = list(range(2 if args.quick else 6))
    sizes = [16, 32] if args.quick else [16, 32, 48]
    duration = 90 if args.quick else 300
    os.makedirs(args.out, exist_ok=True)

    jobs = []
    for n in sizes:
        for v in ORDER:
            for sd in seeds:
                jobs.append(dict(experiment="scaling", variant=v, nodes=n, seed=sd, duration=duration,
                                 traffic_interval=max(1.0, 3.5 * 16 / n)))
    attack_variants = ["Flooding (BitChat TTL=7)", "MARL (full)", "MARL (no IDS)"]
    for v in attack_variants:
        for sd in seeds + [s + 100 for s in seeds]:
            jobs.append(dict(experiment="attack", variant=v, nodes=16, seed=sd, duration=duration,
                             traffic_interval=1.5, attack_at=30.0))

    cold_dur = 240 if args.quick else 600
    for v in COLD_VARIANTS + ["MARL w/o learning (PRoPHET prior)"]:
        for sd in seeds:
            jobs.append(dict(experiment="coldstart", variant=v, nodes=32, seed=sd, duration=cold_dur,
                             traffic_interval=1.5, window=60, cold_start=v in COLD_VARIANTS))

    print(f"Running {len(jobs)} simulations ...")
    with ProcessPoolExecutor() as ex:
        rows = list(ex.map(one_run, jobs))

    keys = sorted({k for r in rows for k in r}, key=lambda k: list(rows[0]).index(k) if k in rows[0] else 99)
    with open(os.path.join(args.out, "runs.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    # ---------------------------------------------------------- summary.md
    lines = ["# Benchmark summary", "",
             f"{len(seeds)} seeds per cell, {duration}s simulated per run; mean ± std.",
             "Energy is in battery-% units summed over all nodes; tx counts include MARL control traffic "
             "(2-hop ACKs, end-to-end ACKs, encounter vector exchange, gossip FL).", ""]
    for n in sizes:
        lines += [f"## {n} nodes", "",
                  "| Variant | PDR | Latency (s) | Tx / delivered msg | Energy / delivered msg | Collisions / msg | SOS PDR |",
                  "|---|---|---|---|---|---|---|"]
        for v in ORDER:
            rs = [r for r in rows if r["experiment"] == "scaling" and r["nodes"] == n and r["variant"] == v]
            lines.append(f"| {v} | {ms([r['pdr'] for r in rs])} | {ms([r['latency_s'] for r in rs])} | "
                         f"{ms([r['tx_per_delivery'] for r in rs])} | {ms([r['energy_per_delivery'] for r in rs])} | "
                         f"{ms([r['collisions_per_msg'] for r in rs])} | {ms([r['sos_pdr'] for r in rs])} |")
        lines.append("")
    lines += ["## Sinkhole attack (16 nodes, attacker = most central node at t=30s)", "",
              "| Variant | PDR after attack | Packets swallowed | Detection time (s) | False positives |", "|---|---|---|---|---|"]
    for v in attack_variants:
        rs = [r for r in rows if r["experiment"] == "attack" and r["variant"] == v]
        det = [r["ids_detection_s"] for r in rs]
        ndet = sum(1 for d in det if not math.isnan(d))
        det_s = f"{ms(det)} ({ndet}/{len(rs)} detected)" if v == "MARL (full)" else "–"
        lines.append(f"| {v} | {ms([r.get('pdr_after_attack') for r in rs])} | {ms([r['sinkhole_drops'] for r in rs])} | "
                     f"{det_s} | {sum(r['false_positives'] for r in rs)} |")
    lines += ["", "## Cold start: learning routing from zero (32 nodes, PDR per 60 s window)", "",
              "| Variant | " + " | ".join(f"{60 * (i + 1)}s" for i in range(cold_dur // 60)) + " |",
              "|---|" + "---|" * (cold_dur // 60)]
    for v in COLD_VARIANTS + ["MARL w/o learning (PRoPHET prior)"]:
        rs = [r for r in rows if r["experiment"] == "coldstart" and r["variant"] == v]
        cells = [f"{st.mean(r[f'pdr_w{i:02d}'] for r in rs):.2f}" for i in range(cold_dur // 60)]
        name = "Expert prior (reference)" if v.startswith("MARL w/o") else v
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    tri = [r for r in rows if r["experiment"] == "scaling" and r["variant"] == "MARL (full)"]
    lines += ["", "## Cognitive triage", "",
              f"- Average message on air: {ms([r['triage_raw_bytes'] for r in tri])} B raw → {ms([r['triage_air_bytes'] for r in tri])} B (incl. 24 B header)",
              f"- SOS messages: {ms([r['sos_raw_bytes'] for r in tri])} B raw → {ms([r['sos_air_bytes'] for r in tri])} B",
              f"- Federated gossip rounds per run (16 nodes): {ms([r['fl_rounds'] for r in tri if r['nodes'] == 16])}", ""]
    with open(os.path.join(args.out, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))

    # --------------------------------------------------------------- charts
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed - skipping charts (pip install matplotlib)")
        return

    plt.rcParams.update({
        "font.size": 11, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": "#52514e",
        "xtick.color": "#52514e", "ytick.color": "#52514e", "axes.grid": True,
        "grid.color": "#e9e8e4", "grid.linewidth": 0.8, "axes.spines.top": False,
        "axes.spines.right": False, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
    })

    def line_chart(metric, ylabel, fname, title):
        fig, ax = plt.subplots(figsize=(7.2, 4.4))
        for v in ORDER:
            means, sds = [], []
            for n in sizes:
                xs = [r[metric] for r in rows if r["experiment"] == "scaling" and r["nodes"] == n and r["variant"] == v
                      and not math.isnan(r[metric])]
                means.append(st.mean(xs) if xs else float("nan"))
                sds.append(st.stdev(xs) if len(xs) > 1 else 0.0)
            ax.errorbar(sizes, means, yerr=sds, color=COLORS[v], marker=MARKERS[v], markersize=7,
                        linewidth=2, capsize=3, label=v)
        ax.set_xticks(sizes)
        ax.set_xlabel("Nodes in the same area (density)")
        ax.set_ylabel(ylabel)
        ax.set_title(title, loc="left", color="#0b0b0b", fontsize=13)
        ax.set_ylim(bottom=0)
        ax.set_axisbelow(True)
        ax.legend(frameon=False, fontsize=9)
        fig.tight_layout()
        fig.savefig(os.path.join(args.out, fname), dpi=160)
        plt.close(fig)

    line_chart("pdr", "Packet delivery ratio", "pdr_vs_density.png", "Delivery ratio")
    line_chart("energy_per_delivery", "Battery % per delivered message", "energy_vs_density.png", "Energy per delivered message")
    line_chart("tx_per_delivery", "Transmissions per delivered message", "tx_vs_density.png", "Transmissions per delivered message")
    line_chart("latency_s", "Mean end-to-end latency (s)", "latency_vs_density.png", "Latency")

    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    vals = [[r.get("pdr_after_attack") for r in rows if r["experiment"] == "attack" and r["variant"] == v] for v in attack_variants]
    means = [st.mean([x for x in vs if x is not None and not math.isnan(x)]) for vs in vals]
    sds = [st.stdev([x for x in vs if x is not None and not math.isnan(x)]) for vs in vals]
    bars = ax.bar(range(len(attack_variants)), means, yerr=sds, capsize=4, width=0.6,
                  color=[COLORS[v] for v in attack_variants], edgecolor="#fcfcfb", linewidth=2)
    ax.set_axisbelow(True)
    for b, m, sd_ in zip(bars, means, sds):
        ax.text(b.get_x() + b.get_width() / 2, m + sd_ + 0.03, f"{m:.0%}", ha="center", color="#0b0b0b", fontsize=11)
    ax.set_xticks(range(len(attack_variants)))
    ax.set_xticklabels(["Flooding", "MARL + trust IDS", "MARL, no IDS"])
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("Delivery ratio after attack")
    ax.set_title("Sinkhole attack at t=30s (16 nodes)", loc="left", color="#0b0b0b", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(args.out, "attack_pdr.png"), dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    xs = [60 * (i + 1) for i in range(cold_dur // 60)]
    ref = [r for r in rows if r["experiment"] == "coldstart" and r["variant"].startswith("MARL w/o")]
    ref_m = st.mean(st.mean(r[f"pdr_w{i:02d}"] for i in range(cold_dur // 60)) for r in ref)
    ax.axhline(ref_m, color="#52514e", linestyle="--", linewidth=1.2)
    ax.text(xs[0], ref_m + 0.02, f"hand-designed prior ({ref_m:.2f})", color="#52514e", fontsize=9)
    for v in COLD_VARIANTS:
        rs = [r for r in rows if r["experiment"] == "coldstart" and r["variant"] == v]
        m = [st.mean(r[f"pdr_w{i:02d}"] for r in rs) for i in range(len(xs))]
        sd = [st.stdev([r[f"pdr_w{i:02d}"] for r in rs]) if len(rs) > 1 else 0 for i in range(len(xs))]
        ax.plot(xs, m, color=COLORS[v], marker="o", markersize=6, linewidth=2, label=v)
        ax.fill_between(xs, [a - b for a, b in zip(m, sd)], [a + b for a, b in zip(m, sd)], color=COLORS[v], alpha=0.12, linewidth=0)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("Simulated time (s)")
    ax.set_ylabel("Delivery ratio in window")
    ax.set_title("Learning to route from zero (32 nodes)", loc="left", color="#0b0b0b", fontsize=13)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    fig.tight_layout()
    fig.savefig(os.path.join(args.out, "coldstart_learning.png"), dpi=160)
    plt.close(fig)
    print(f"Charts written to {args.out}/")


if __name__ == "__main__":
    main()
