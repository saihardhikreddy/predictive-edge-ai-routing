"""Link-survival prediction: (A) how well it predicts, (B) whether routing benefits.

(A) Every node learns its own model online (simulation/link_predictor.py); predictions are scored
    test-then-train after a 60 s warm-up. Models: trend (RSSI + slope + link age), RSSI only,
    and two baselines (always survives, running base rate). 16 nodes, mobility x1/x2/x4/x8.
(B) Learned routing with and without prediction on identical traces, for the three ways of using
    it (horizon discount, per-hop discount, last-chance handoff). 16 and 32 nodes, mobility x1/x4/x8.

    python tools/link_prediction_benchmark.py          # 6 seeds x 300 s
    python tools/link_prediction_benchmark.py --quick  # 2 seeds x 120 s
"""
import argparse
import os
import statistics as st
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from benchmark import one_run  # noqa: E402
from simulation.link_predictor import calibration, metrics  # noqa: E402

MOB_A = [1, 2, 4, 8]
MOB_B = [1, 4, 8]
MODES = [None, "horizon", "hop", "handoff"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="results")
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()
    seeds = list(range(2 if a.quick else 6))
    dur = 120 if a.quick else 300
    ja = [dict(experiment="pred", variant="MARL (full)", nodes=16, seed=s, duration=dur, traffic_interval=3.5,
               track_links=True, mobility=m) for m in MOB_A for s in seeds]
    jb = [dict(experiment="route", variant="MARL (full)", nodes=n, seed=s, duration=dur,
               traffic_interval=max(1.0, 3.5 * 16 / n), mobility=m, predict_links=md is not None, pred_mode=md or "hop")
          for n in (16, 32) for m in MOB_B for md in MODES for s in seeds]
    print(f"Running {len(ja) + len(jb)} simulations ...", flush=True)
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        ra = list(ex.map(one_run, ja))
        rb = list(ex.map(one_run, jb))

    out = ["# Link-survival prediction", "",
           f"{len(seeds)} seeds per cell, {dur} s per run. Target: the neighbour is still heard at every beacon for the next 3 s.",
           "Scored test-then-train after a 60 s warm-up; pooled over all nodes and seeds. AUC = chance a surviving link is ranked",
           "above a breaking one (0.5 = guessing). Brier = mean squared error of the probability (lower is better).", "",
           "## A. Prediction quality (16 nodes)", "",
           "| Mobility | Links that break | Model | AUC | Brier | Log loss | Breaks flagged (recall) | Precision |", "|---|---|---|---|---|---|---|---|"]
    for m in MOB_A:
        sel = [r for r, j in zip(ra, ja) if j["mobility"] == m]
        for model, name in (("trend", "Trend (RSSI + slope + age)"), ("rssi", "RSSI only"), ("base_rate", "Base rate"), ("always", "Always survives")):
            pairs = [p for r in sel for p in r["link_pred_pairs"][model]]
            d = metrics(pairs)
            out.append(f"| x{m} | {d['break_rate'] * 100:.1f} % | {name} | {d['auc']:.3f} | {d['brier']:.4f} | {d['log_loss']:.3f} | "
                       f"{d['recall'] * 100:.0f} % | {d['precision'] * 100:.0f} % |")
    out += ["", "Calibration of the trend model at x4 (mean predicted vs observed survival, count):", ""]
    pairs = [p for r, j in zip(ra, ja) if j["mobility"] == 4 for p in r["link_pred_pairs"]["trend"]]
    out += ["| Predicted | Observed | Count |", "|---|---|---|"] + [f"| {p:.2f} | {o:.2f} | {n} |" for p, o, n in calibration(pairs)]

    def c(sel, k):
        xs = [r[k] for r in sel if r[k] == r[k]]
        return f"{st.mean(xs):.3f} ± {st.stdev(xs):.3f}" if len(xs) > 1 else "–"

    out += ["", "## B. Routing with and without prediction", "",
            "| Nodes | Mobility | Router | PDR | Latency (s) | Link failures | Energy / delivered |", "|---|---|---|---|---|---|---|"]
    names = {None: "Learned routing", "horizon": "+ prediction (3-s discount)", "hop": "+ prediction (per-hop discount)", "handoff": "+ prediction (last-chance handoff)"}
    for n in (16, 32):
        for m in MOB_B:
            for md in MODES:
                sel = [r for r, j in zip(rb, jb) if j["nodes"] == n and j["mobility"] == m and (j["predict_links"] == (md is not None)) and (md is None or j["pred_mode"] == md)]
                out.append(f"| {n} | x{m} | {names[md]} | {c(sel, 'pdr')} | {c(sel, 'latency_s')} | {c(sel, 'link_breaks')} | {c(sel, 'energy_per_delivery')} |")
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "link_prediction.md"), "w") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
