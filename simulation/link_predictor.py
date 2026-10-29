"""Link-survival prediction for a mobile Bluetooth mesh.

Target: Y_ij(t, H) = 1 if node j stays in i's neighbour table at every beacon in (t, t + H].
Each node i learns its own model online from the RSSI it hears in j's beacons (once per second),
so no node needs positions, GPS or anyone else's data:

    features  x = [1, rssi_norm, slope_norm, age_norm]
      rssi_norm  = (smoothed RSSI + 70) / 10
      slope_norm = least-squares RSSI slope over the last 5 beacons (dB/s) / 2, clipped
      age_norm   = min(link age, 30 s) / 30
    model     p = sigmoid(w . x), trained by SGD on log loss with light L2

Learning is prequential (test-then-train): a prediction made at time t is scored when its label
resolves at t + H, and only then used to update the weights. A prediction can therefore never
use information from its own future; this is the temporal train/test separation.

Two models are kept side by side so the value of the trend feature can be measured:
"trend" (all features) and "rssi" (bias + RSSI only). Baselines scored on the same predictions:
"always" (link always survives) and "base_rate" (running share of links that survived).
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

HORIZON_S = 3.0
WARMUP_S = 60.0  # predictions made before this are used for training but not scored
HISTORY = 5
LR = 0.05
L2 = 1e-4
MODELS = ("trend", "rssi")


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _slope(hist: Deque[Tuple[float, float]]) -> float:
    if len(hist) < 2:
        return 0.0
    ts = [t for t, _ in hist]
    rs = [r for _, r in hist]
    mt, mr = sum(ts) / len(ts), sum(rs) / len(rs)
    den = sum((t - mt) ** 2 for t in ts)
    return 0.0 if den <= 1e-9 else sum((t - mt) * (r - mr) for t, r in zip(ts, rs)) / den


@dataclass
class _Link:
    hist: Deque[Tuple[float, float]] = field(default_factory=lambda: deque(maxlen=HISTORY))
    since: float = 0.0
    present: bool = False
    losses: Deque[float] = field(default_factory=lambda: deque(maxlen=16))


@dataclass
class _Pending:
    peer: str
    t0: float
    x: List[float]
    p: Dict[str, float]


class LinkPredictor:
    """One per node."""

    def __init__(self, horizon_s: float = HORIZON_S):
        self.h = horizon_s
        self.w: Dict[str, List[float]] = {"trend": [2.0, 0.5, 0.0, 0.0], "rssi": [2.0, 0.5]}
        self.links: Dict[str, _Link] = {}
        self.pending: List[_Pending] = []
        self.survived = 0
        self.resolved = 0
        # (model -> list of (p, y)) for evaluation
        self.scored: Dict[str, List[Tuple[float, int]]] = {m: [] for m in MODELS + ("always", "base_rate")}

    # ------------------------------------------------------------ features

    def features(self, peer: str, t: float) -> Optional[List[float]]:
        ln = self.links.get(peer)
        if ln is None or not ln.present or not ln.hist:
            return None
        rs = [r for _, r in ln.hist]
        rssi = 0.6 * rs[-1] + 0.4 * (sum(rs) / len(rs))
        slope = max(-10.0, min(10.0, _slope(ln.hist)))
        age = min(t - ln.since, 30.0)
        return [1.0, (rssi + 70.0) / 10.0, slope / 2.0, age / 30.0]

    def _p(self, model: str, x: List[float]) -> float:
        w = self.w[model]
        return _sigmoid(sum(a * b for a, b in zip(w, x[: len(w)])))

    def predict(self, peer: str, t: float, model: str = "trend") -> float:
        """P(link to peer survives the next horizon). 1.0 when there is no history yet."""
        x = self.features(peer, t)
        return 1.0 if x is None else self._p(model, x)

    # ------------------------------------------------------------ observations

    def observe(self, t: float, neighbours: Dict[str, float], record: bool = True):
        """Call once per beacon with {peer: rssi} of everyone heard right now."""
        for peer, rssi in neighbours.items():
            ln = self.links.setdefault(peer, _Link())
            if not ln.present:
                ln.present, ln.since = True, t
                ln.hist.clear()
            ln.hist.append((t, float(rssi)))
        for peer, ln in self.links.items():
            if ln.present and peer not in neighbours:
                ln.present = False
                ln.losses.append(t)
        self._resolve(t)
        if record:
            for peer in neighbours:
                x = self.features(peer, t)
                if x is not None and len(self.links[peer].hist) >= 2:
                    self.pending.append(_Pending(peer, t, x, {m: self._p(m, x) for m in MODELS}))

    def _resolve(self, t: float):
        keep: List[_Pending] = []
        for pd in self.pending:
            ln = self.links[pd.peer]
            broke = any(pd.t0 < lt <= pd.t0 + self.h for lt in ln.losses)
            if not broke and t < pd.t0 + self.h:
                keep.append(pd)
                continue
            y = 0 if broke else 1
            # test ...
            if pd.t0 >= WARMUP_S:
                for m in MODELS:
                    self.scored[m].append((pd.p[m], y))
                self.scored["always"].append((1.0, y))
                base = (self.survived + 1) / (self.resolved + 2)
                self.scored["base_rate"].append((base, y))
            # ... then train
            self.resolved += 1
            self.survived += y
            for m in MODELS:
                w = self.w[m]
                x = pd.x[: len(w)]
                err = self._p(m, pd.x) - y
                self.w[m] = [wi - LR * (err * xi + L2 * wi) for wi, xi in zip(w, x)]
        self.pending = keep


# ---------------------------------------------------------------- metrics

def metrics(pairs: List[Tuple[float, int]]) -> Dict[str, float]:
    if not pairs:
        return {}
    eps = 1e-6
    n = len(pairs)
    brier = sum((p - y) ** 2 for p, y in pairs) / n
    ll = -sum(y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps)) for p, y in pairs) / n
    # "will break" is the event that matters for routing: score it as the positive class
    tp = sum(1 for p, y in pairs if p < 0.5 and y == 0)
    fp = sum(1 for p, y in pairs if p < 0.5 and y == 1)
    fn = sum(1 for p, y in pairs if p >= 0.5 and y == 0)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    # AUC (probability a breaking link is ranked below a surviving one), ties count half
    pos = sorted(p for p, y in pairs if y == 1)
    neg = [p for p, y in pairs if y == 0]
    auc = float("nan")
    if pos and neg:
        import bisect
        s = 0.0
        for q in neg:
            lo = bisect.bisect_left(pos, q)
            hi = bisect.bisect_right(pos, q)
            s += (len(pos) - hi) + 0.5 * (hi - lo)
        auc = s / (len(pos) * len(neg))
    return {"n": n, "break_rate": 1 - sum(y for _, y in pairs) / n, "brier": brier, "log_loss": ll,
            "precision": prec, "recall": rec, "f1": f1, "auc": auc}


def calibration(pairs: List[Tuple[float, int]], bins: int = 5) -> List[Tuple[float, float, int]]:
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(p, y) for p, y in pairs if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if sel:
            out.append((sum(p for p, _ in sel) / len(sel), sum(y for _, y in sel) / len(sel), len(sel)))
    return out
