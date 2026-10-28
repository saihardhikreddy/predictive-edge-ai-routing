"""Bluetooth 5 Long Range (LE Coded PHY) vs normal 1M PHY on the same layouts and traffic.

Coded PHY model: links up to 2x the 1M range, +12 dB sensitivity on those far links,
8x airtime/energy per frame and 2x hop time on them. Same seeds = same mobility and traffic.

    python tools/long_range_benchmark.py            # 6 seeds, 300 s, 8/16/32 nodes
    python tools/long_range_benchmark.py --quick    # 2 seeds, 120 s
"""
import argparse
import os
import statistics as st
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from benchmark import one_run  # noqa: E402

VARIANTS = ["Flooding (BitChat TTL=7)", "MARL (full)"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="results")
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()
    seeds = list(range(2 if a.quick else 6))
    dur = 120 if a.quick else 300
    sizes = [8, 16, 32]
    jobs = [dict(experiment="longrange", variant=v, nodes=n, seed=s, duration=dur,
                 traffic_interval=max(1.0, 3.5 * 16 / n), long_range=lr)
            for n in sizes for v in VARIANTS for lr in (False, True) for s in seeds]
    print(f"Running {len(jobs)} simulations ...", flush=True)
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        rows = list(ex.map(one_run, jobs))
    for r, j in zip(rows, jobs):
        r["long_range"] = j["long_range"]

    def cell(n, v, lr, k):
        xs = [r[k] for r in rows if r["nodes"] == n and r["variant"] == v and r["long_range"] == lr]
        xs = [x for x in xs if x == x]
        return f"{st.mean(xs):.2f} ± {st.stdev(xs):.2f}" if len(xs) > 1 else (f"{xs[0]:.2f}" if xs else "–")

    lines = ["# Bluetooth 5 Long Range vs normal range", "",
             f"{len(seeds)} seeds per cell, {dur} s simulated per run; mean ± std. Coded PHY: 2x range, "
             "+12 dB on far links, 8x energy and 2x hop time per Coded frame.", ""]
    for n in sizes:
        lines += [f"## {n} nodes", "",
                  "| Variant | Radio | PDR | Latency (s) | Hops | Energy / delivered msg | Collisions / msg |",
                  "|---|---|---|---|---|---|---|"]
        for v in VARIANTS:
            for lr in (False, True):
                lines.append(f"| {v} | {'Long Range' if lr else 'Normal'} | {cell(n, v, lr, 'pdr')} | "
                             f"{cell(n, v, lr, 'latency_s')} | {cell(n, v, lr, 'hops')} | "
                             f"{cell(n, v, lr, 'energy_per_delivery')} | {cell(n, v, lr, 'collisions_per_msg')} |")
        lines.append("")
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "long_range.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
