# Benchmark summary

6 seeds per cell, 300s simulated per run; mean ± std.
Energy is in battery-% units summed over all nodes; tx counts include MARL control traffic (2-hop ACKs, end-to-end ACKs, encounter vector exchange, gossip FL).

## 16 nodes

| Variant | PDR | Latency (s) | Tx / delivered msg | Energy / delivered msg | Collisions / msg | SOS PDR |
|---|---|---|---|---|---|---|
| Flooding (BitChat TTL=7) | 0.78 ± 0.09 | 0.89 ± 0.06 | 15.05 ± 0.76 | 1.77 ± 0.13 | 17.80 ± 5.12 | 0.77 ± 0.10 |
| MARL (full) | 0.89 ± 0.05 | 7.29 ± 2.62 | 17.95 ± 2.71 | 0.81 ± 0.06 | 0.00 ± 0.00 | 0.96 ± 0.05 |
| MARL w/o learning (PRoPHET prior) | 0.87 ± 0.07 | 8.27 ± 2.52 | 17.25 ± 2.74 | 0.80 ± 0.07 | 0.00 ± 0.00 | 0.94 ± 0.09 |
| MARL w/o federated gossip | 0.90 ± 0.04 | 7.54 ± 1.96 | 16.53 ± 1.73 | 0.78 ± 0.04 | 0.00 ± 0.00 | 0.97 ± 0.05 |

## 32 nodes

| Variant | PDR | Latency (s) | Tx / delivered msg | Energy / delivered msg | Collisions / msg | SOS PDR |
|---|---|---|---|---|---|---|
| Flooding (BitChat TTL=7) | 0.96 ± 0.01 | 0.92 ± 0.05 | 30.86 ± 0.21 | 6.54 ± 0.18 | 180 ± 17 | 0.95 ± 0.05 |
| MARL (full) | 0.92 ± 0.02 | 4.65 ± 0.37 | 24.79 ± 1.53 | 1.35 ± 0.06 | 0.00 ± 0.00 | 0.96 ± 0.04 |
| MARL w/o learning (PRoPHET prior) | 0.91 ± 0.02 | 4.50 ± 0.51 | 24.02 ± 1.66 | 1.33 ± 0.05 | 0.00 ± 0.00 | 0.95 ± 0.06 |
| MARL w/o federated gossip | 0.93 ± 0.02 | 4.77 ± 0.61 | 23.16 ± 1.09 | 1.30 ± 0.04 | 0.00 ± 0.00 | 0.97 ± 0.04 |

## 48 nodes

| Variant | PDR | Latency (s) | Tx / delivered msg | Energy / delivered msg | Collisions / msg | SOS PDR |
|---|---|---|---|---|---|---|
| Flooding (BitChat TTL=7) | 0.99 ± 0.01 | 0.89 ± 0.04 | 47.03 ± 0.18 | 13.54 ± 0.64 | 528 ± 39 | 0.99 ± 0.01 |
| MARL (full) | 0.90 ± 0.01 | 3.93 ± 0.15 | 31.76 ± 0.95 | 1.88 ± 0.07 | 0.00 ± 0.00 | 0.92 ± 0.04 |
| MARL w/o learning (PRoPHET prior) | 0.88 ± 0.01 | 3.24 ± 0.23 | 31.77 ± 0.91 | 1.89 ± 0.05 | 0.00 ± 0.00 | 0.91 ± 0.03 |
| MARL w/o federated gossip | 0.90 ± 0.02 | 3.88 ± 0.23 | 30.26 ± 0.83 | 1.83 ± 0.07 | 0.00 ± 0.00 | 0.92 ± 0.03 |

## Sinkhole attack (16 nodes, attacker = most central node at t=30s)

| Variant | PDR after attack | Packets swallowed | Detection time (s) | False positives |
|---|---|---|---|---|
| Flooding (BitChat TTL=7) | 0.77 ± 0.08 | 0.00 ± 0.00 | – | 0 |
| MARL (full) | 0.85 ± 0.04 | 17.42 ± 2.61 | 43.84 ± 11.28 (12/12 detected) | 0 |
| MARL (no IDS) | 0.64 ± 0.08 | 75.58 ± 15.97 | – | 0 |

## Cold start: learning routing from zero (32 nodes, PDR per 60 s window)

| Variant | 60s | 120s | 180s | 240s | 300s | 360s | 420s | 480s | 540s | 600s |
|---|---|---|---|---|---|---|---|---|---|---|
| Cold start, no learning | 0.18 | 0.21 | 0.21 | 0.19 | 0.26 | 0.23 | 0.24 | 0.23 | 0.22 | 0.25 |
| Cold start + TD learning | 0.32 | 0.56 | 0.68 | 0.61 | 0.67 | 0.70 | 0.78 | 0.70 | 0.83 | 0.76 |
| Cold start + TD + gossip FL | 0.35 | 0.72 | 0.72 | 0.64 | 0.77 | 0.80 | 0.86 | 0.81 | 0.86 | 0.80 |
| Expert prior (reference) | 0.88 | 0.93 | 0.91 | 0.88 | 0.94 | 0.94 | 0.94 | 0.92 | 0.96 | 0.87 |

## Cognitive triage

- Average message on air: 95.27 ± 0.84 B raw → 56.23 ± 1.24 B (incl. 24 B header)
- SOS messages: 113 ± 1 B raw → 29.53 ± 0.17 B
- Federated gossip rounds per run (16 nodes): 35.33 ± 3.20
