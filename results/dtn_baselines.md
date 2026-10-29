# Learned routing vs standard DTN baselines

6 seeds per cell, 300 s per run, identical mobility, radio, traffic and energy model; mean ± std.
Multi-copy baselines keep their copies until TTL (no anti-packets); rows marked 'instant purge' delete every copy the moment
a message is delivered, an optimistic upper bound for them. See simulation/dtn_baselines.py.

## 16 nodes

| Variant | PDR | SOS PDR | Latency (s) | Hops | Tx / delivered | Energy / delivered |
|---|---|---|---|---|---|---|
| Flooding (BitChat TTL=7) | 0.78 ± 0.09 | 0.77 ± 0.10 | 0.89 ± 0.06 | 2.21 ± 0.15 | 15.05 ± 0.76 | 1.77 ± 0.13 |
| Epidemic | 1.00 ± 0.01 | 0.99 ± 0.02 | 1.66 ± 1.06 | 2.52 ± 0.24 | 52.98 ± 2.15 | 0.94 ± 0.04 |
| Spray-and-Wait (L=8) | 0.96 ± 0.02 | 0.98 ± 0.05 | 5.16 ± 1.43 | 2.14 ± 0.21 | 29.18 ± 1.87 | 0.50 ± 0.03 |
| PRoPHET (GRTR) | 0.99 ± 0.01 | 0.98 ± 0.05 | 2.98 ± 1.52 | 2.20 ± 0.15 | 42.89 ± 2.29 | 0.99 ± 0.05 |
| Direct delivery | 0.65 ± 0.07 | 0.76 ± 0.12 | 12.93 ± 2.61 | 1.00 ± 0.00 | 6.93 ± 0.51 | 0.10 ± 0.01 |
| MARL (full) | 0.89 ± 0.05 | 0.96 ± 0.05 | 7.29 ± 2.62 | 3.26 ± 0.45 | 17.95 ± 2.71 | 0.81 ± 0.06 |
| Epidemic, instant purge | 1.00 ± 0.00 | 0.99 ± 0.02 | 1.44 ± 0.91 | 2.57 ± 0.26 | 36.15 ± 1.42 | 0.63 ± 0.03 |
| Spray-and-Wait (L=8), instant purge | 0.96 ± 0.02 | 0.98 ± 0.05 | 4.99 ± 1.60 | 2.14 ± 0.21 | 22.77 ± 1.17 | 0.39 ± 0.02 |
| PRoPHET (GRTR), instant purge | 0.99 ± 0.01 | 0.99 ± 0.02 | 2.68 ± 1.16 | 2.24 ± 0.16 | 20.28 ± 1.49 | 0.60 ± 0.02 |

## 32 nodes

| Variant | PDR | SOS PDR | Latency (s) | Hops | Tx / delivered | Energy / delivered |
|---|---|---|---|---|---|---|
| Flooding (BitChat TTL=7) | 0.96 ± 0.01 | 0.95 ± 0.05 | 0.92 ± 0.05 | 2.31 ± 0.12 | 30.86 ± 0.21 | 6.54 ± 0.18 |
| Epidemic | 1.00 ± 0.00 | 1.00 ± 0.00 | 0.32 ± 0.15 | 2.50 ± 0.14 | 104.32 ± 3.48 | 1.88 ± 0.08 |
| Spray-and-Wait (L=8) | 0.94 ± 0.03 | 0.96 ± 0.05 | 4.45 ± 0.98 | 2.19 ± 0.11 | 29.58 ± 1.73 | 0.51 ± 0.03 |
| PRoPHET (GRTR) | 1.00 ± 0.00 | 1.00 ± 0.00 | 0.72 ± 0.19 | 2.32 ± 0.13 | 90.43 ± 5.42 | 2.08 ± 0.09 |
| Direct delivery | 0.63 ± 0.08 | 0.72 ± 0.14 | 12.62 ± 3.29 | 1.00 ± 0.00 | 7.12 ± 0.91 | 0.10 ± 0.01 |
| MARL (full) | 0.92 ± 0.02 | 0.96 ± 0.04 | 4.65 ± 0.37 | 3.92 ± 0.19 | 24.79 ± 1.53 | 1.35 ± 0.06 |
| Epidemic, instant purge | 1.00 ± 0.00 | 1.00 ± 0.00 | 0.24 ± 0.13 | 2.49 ± 0.13 | 79.94 ± 4.47 | 1.43 ± 0.09 |
| Spray-and-Wait (L=8), instant purge | 0.94 ± 0.02 | 0.98 ± 0.04 | 4.70 ± 0.94 | 2.19 ± 0.12 | 25.17 ± 1.23 | 0.43 ± 0.03 |
| PRoPHET (GRTR), instant purge | 1.00 ± 0.00 | 1.00 ± 0.00 | 0.66 ± 0.12 | 2.31 ± 0.11 | 34.55 ± 3.30 | 1.08 ± 0.07 |

## 48 nodes

| Variant | PDR | SOS PDR | Latency (s) | Hops | Tx / delivered | Energy / delivered |
|---|---|---|---|---|---|---|
| Flooding (BitChat TTL=7) | 0.99 ± 0.01 | 0.99 ± 0.01 | 0.89 ± 0.04 | 2.22 ± 0.10 | 47.03 ± 0.18 | 13.54 ± 0.64 |
| Epidemic | 1.00 ± 0.00 | 1.00 ± 0.00 | 0.13 ± 0.01 | 2.46 ± 0.08 | 156.27 ± 1.43 | 2.76 ± 0.03 |
| Spray-and-Wait (L=8) | 0.93 ± 0.01 | 0.96 ± 0.03 | 4.46 ± 0.32 | 2.11 ± 0.04 | 28.73 ± 0.59 | 0.49 ± 0.01 |
| PRoPHET (GRTR) | 1.00 ± 0.00 | 1.00 ± 0.00 | 0.47 ± 0.06 | 2.31 ± 0.08 | 137.54 ± 2.47 | 3.10 ± 0.04 |
| Direct delivery | 0.62 ± 0.03 | 0.71 ± 0.06 | 11.04 ± 1.31 | 1.00 ± 0.00 | 6.64 ± 0.41 | 0.10 ± 0.00 |
| MARL (full) | 0.90 ± 0.01 | 0.92 ± 0.04 | 3.93 ± 0.15 | 4.28 ± 0.09 | 31.76 ± 0.95 | 1.88 ± 0.07 |
| Epidemic, instant purge | 1.00 ± 0.00 | 1.00 ± 0.00 | 0.14 ± 0.03 | 2.45 ± 0.07 | 122.93 ± 2.40 | 2.17 ± 0.03 |
| Spray-and-Wait (L=8), instant purge | 0.94 ± 0.01 | 0.97 ± 0.02 | 4.54 ± 0.62 | 2.10 ± 0.07 | 24.75 ± 0.28 | 0.42 ± 0.01 |
| PRoPHET (GRTR), instant purge | 1.00 ± 0.00 | 1.00 ± 0.00 | 0.45 ± 0.06 | 2.30 ± 0.07 | 49.17 ± 2.14 | 1.53 ± 0.04 |

## Sinkhole at t = 30 s (16 nodes, most central node)

| Variant | PDR after attack | Packets swallowed |
|---|---|---|
| Flooding (BitChat TTL=7) | 0.77 ± 0.08 | 0.00 ± 0.00 |
| Epidemic | 1.00 ± 0.02 | 2473.08 ± 615.01 |
| Spray-and-Wait (L=8) | 0.95 ± 0.02 | 122.17 ± 43.21 |
| PRoPHET (GRTR) | 0.99 ± 0.02 | 2470.17 ± 614.27 |
| Direct delivery | 0.65 ± 0.07 | 0.00 ± 0.00 |
| MARL (full) | 0.85 ± 0.04 | 17.42 ± 2.61 |
