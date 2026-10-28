# Bluetooth 5 Long Range vs normal range

6 seeds per cell, 300 s simulated per run; mean ± std. Coded PHY: 2x range, +12 dB on far links, 8x energy and 2x hop time per Coded frame.

## 8 nodes

| Variant | Radio | PDR | Latency (s) | Hops | Energy / delivered msg | Collisions / msg |
|---|---|---|---|---|---|---|
| Flooding (BitChat TTL=7) | Normal | 0.42 ± 0.12 | 0.57 ± 0.05 | 1.43 ± 0.11 | 0.60 ± 0.06 | 0.96 ± 0.62 |
| Flooding (BitChat TTL=7) | Long Range | 0.96 ± 0.02 | 0.59 ± 0.03 | 1.46 ± 0.07 | 4.49 ± 0.42 | 8.22 ± 0.52 |
| MARL (full) | Normal | 0.76 ± 0.13 | 10.34 ± 1.85 | 2.21 ± 0.28 | 0.51 ± 0.04 | 0.00 ± 0.00 |
| MARL (full) | Long Range | 0.99 ± 0.01 | 2.36 ± 0.57 | 1.38 ± 0.17 | 0.82 ± 0.08 | 0.00 ± 0.00 |

## 16 nodes

| Variant | Radio | PDR | Latency (s) | Hops | Energy / delivered msg | Collisions / msg |
|---|---|---|---|---|---|---|
| Flooding (BitChat TTL=7) | Normal | 0.78 ± 0.09 | 0.89 ± 0.06 | 2.21 ± 0.15 | 1.77 ± 0.13 | 17.80 ± 5.12 |
| Flooding (BitChat TTL=7) | Long Range | 0.99 ± 0.01 | 0.60 ± 0.03 | 1.51 ± 0.07 | 15.72 ± 0.61 | 85.75 ± 5.11 |
| MARL (full) | Normal | 0.89 ± 0.05 | 7.29 ± 2.62 | 3.26 ± 0.45 | 0.81 ± 0.06 | 0.00 ± 0.00 |
| MARL (full) | Long Range | 0.99 ± 0.00 | 2.66 ± 0.61 | 1.66 ± 0.19 | 1.36 ± 0.07 | 0.00 ± 0.00 |

## 32 nodes

| Variant | Radio | PDR | Latency (s) | Hops | Energy / delivered msg | Collisions / msg |
|---|---|---|---|---|---|---|
| Flooding (BitChat TTL=7) | Normal | 0.96 ± 0.01 | 0.92 ± 0.05 | 2.31 ± 0.12 | 6.54 ± 0.18 | 180.45 ± 17.35 |
| Flooding (BitChat TTL=7) | Long Range | 0.88 ± 0.13 | 0.56 ± 0.04 | 1.40 ± 0.09 | 26.78 ± 5.94 | 244.86 ± 72.14 |
| MARL (full) | Normal | 0.92 ± 0.02 | 4.65 ± 0.37 | 3.92 ± 0.19 | 1.35 ± 0.06 | 0.00 ± 0.00 |
| MARL (full) | Long Range | 0.99 ± 0.00 | 2.58 ± 0.29 | 1.80 ± 0.13 | 2.22 ± 0.04 | 0.00 ± 0.00 |

