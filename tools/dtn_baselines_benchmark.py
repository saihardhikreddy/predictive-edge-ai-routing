"""Learned routing vs flooding and the standard DTN baselines on identical traces.

    python tools/dtn_baselines_benchmark.py          # 6 seeds x 300 s, 16/32/48 nodes
    python tools/dtn_baselines_benchmark.py --quick  # 2 seeds x 120 s
"""
import argparse
import os
import statistics as st
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from benchmark import one_run  # noqa: E402

VARIANTS = ["Flooding (BitChat TTL=7)", "Epidemic", "Spray-and-Wait (L=8)", "PRoPHET (GRTR)", "Direct delivery", "MARL (full)"]
MULTI = ["Epidemic", "Spray-and-Wait (L=8)", "PRoPHET (GRTR)"]
METRICS = [("pdr", "PDR"), ("sos_pdr", "SOS PDR"), ("latency_s", "Latency (s)"), ("hops", "Hops"),
           ("tx_per_delivery", "Tx / delivered"), ("energy_per_delivery", "Energy / delivered")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="results")
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()
    seeds = list(range(2 if a.quick else 6))
    dur = 120 if a.quick else 300
    sizes = [16, 32] if a.quick else [16, 32, 48]
    jobs = [dict(experiment="dtn", variant=v, nodes=n, seed=s, duration=dur, traffic_interval=max(1.0, 3.5 * 16 / n))
            for n in sizes for v in VARIANTS for s in seeds]
    jobs += [dict(experiment="dtn_vaccine", variant=v, nodes=n, seed=s, duration=dur, traffic_interval=max(1.0, 3.5 * 16 / n), vaccine=True)
             for n in sizes for v in MULTI for s in seeds]
    attack = [dict(experiment="dtn_attack", variant=v, nodes=16, seed=s, duration=dur, traffic_interval=1.5, attack_at=30.0)
              for v in VARIANTS for s in seeds + [x + 100 for x in seeds]]
    print(f"Running {len(jobs) + len(attack)} simulations ...", flush=True)
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        rows = list(ex.map(one_run, jobs + attack))

    def cell(sel, k):
        xs = [r[k] for r in sel if r.get(k) == r.get(k)]
        return f"{st.mean(xs):.2f} ± {st.stdev(xs):.2f}" if len(xs) > 1 else "–"

    out = ["# Learned routing vs standard DTN baselines", "",
           f"{len(seeds)} seeds per cell, {dur} s per run, identical mobility, radio, traffic and energy model; mean ± std.",
           "Multi-copy baselines keep their copies until TTL (no anti-packets); rows marked 'instant purge' delete every copy the moment",
           "a message is delivered, an optimistic upper bound for them. See simulation/dtn_baselines.py.", ""]
    for n in sizes:
        out += [f"## {n} nodes", "", "| Variant | " + " | ".join(h for _, h in METRICS) + " |", "|---" * (len(METRICS) + 1) + "|"]
        for v in VARIANTS:
            sel = [r for r in rows if r["experiment"] == "dtn" and r["nodes"] == n and r["variant"] == v]
            out.append(f"| {v} | " + " | ".join(cell(sel, k) for k, _ in METRICS) + " |")
        for v in MULTI:
            sel = [r for r in rows if r["experiment"] == "dtn_vaccine" and r["nodes"] == n and r["variant"] == v]
            out.append(f"| {v}, instant purge | " + " | ".join(cell(sel, k) for k, _ in METRICS) + " |")
        out.append("")
    out += ["## Sinkhole at t = 30 s (16 nodes, most central node)", "", "| Variant | PDR after attack | Packets swallowed |", "|---|---|---|"]
    for v in VARIANTS:
        sel = [r for r in rows if r["experiment"] == "dtn_attack" and r["variant"] == v]
        out.append(f"| {v} | {cell(sel, 'pdr_after_attack')} | {cell(sel, 'sinkhole_drops')} |")
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "dtn_baselines.md"), "w") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
