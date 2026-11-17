# Learned routing vs standard DTN baselines

6 seeds per cell, 300 s per run, identical mobility, radio, traffic and energy model; mean ± std.
Multi-copy baselines keep their copies until TTL (no anti-packets); rows marked 'instant purge' delete every copy the moment
a message is delivered, an optimistic upper bound for them. See simulation/dtn_baselines.py.

## 16 nodes

| Variant | PDR | SOS PDR | Latency (s) | Hops | Tx / delivered | Energy / delivered |
|---|---|---|---|---|---|---|
| Flooding (BitChat TTL=7) | 0.78 ± 0.09 | 0.77 ± 0.10 | 0.89 ± 0.06 | 2.21 ± 0.15 | 15.05 ± 0.76 | 1.77 ± 0.13 |
| Epidemic | 0.99 ± 0.01 | 0.98 ± 0.05 | 2.63 ± 1.16 | 2.28 ± 0.23 | 55.02 ± 2.12 | 0.97 ± 0.04 |
| Spray-and-Wait (L=8) | 0.95 ± 0.03 | 0.98 ± 0.05 | 5.91 ± 1.53 | 2.08 ± 0.15 | 29.20 ± 1.63 | 0.50 ± 0.02 |
| PRoPHET (GRTR) | 0.99 ± 0.01 | 0.98 ± 0.05 | 3.85 ± 1.41 | 2.13 ± 0.17 | 42.74 ± 1.71 | 0.99 ± 0.04 |
| Direct delivery | 0.65 ± 0.07 | 0.76 ± 0.12 | 13.33 ± 2.61 | 1.00 ± 0.00 | 6.93 ± 0.51 | 0.10 ± 0.01 |
| MARL (full) | 0.89 ± 0.05 | 0.96 ± 0.05 | 7.29 ± 2.62 | 3.26 ± 0.45 | 17.95 ± 2.71 | 0.81 ± 0.06 |
| Epidemic, instant purge | 0.99 ± 0.01 | 0.98 ± 0.05 | 2.34 ± 0.92 | 2.31 ± 0.18 | 35.91 ± 1.73 | 0.62 ± 0.04 |
| Spray-and-Wait (L=8), instant purge | 0.96 ± 0.03 | 0.98 ± 0.05 | 5.95 ± 1.54 | 2.06 ± 0.15 | 22.21 ± 1.55 | 0.38 ± 0.03 |
| PRoPHET (GRTR), instant purge | 0.99 ± 0.01 | 0.98 ± 0.05 | 3.50 ± 1.35 | 2.15 ± 0.14 | 21.85 ± 1.72 | 0.62 ± 0.03 |

## 32 nodes

| Variant | PDR | SOS PDR | Latency (s) | Hops | Tx / delivered | Energy / delivered |
|---|---|---|---|---|---|---|
| Flooding (BitChat TTL=7) | 0.96 ± 0.01 | 0.95 ± 0.05 | 0.92 ± 0.05 | 2.31 ± 0.12 | 30.86 ± 0.21 | 6.54 ± 0.18 |
| Epidemic | 1.00 ± 0.00 | 0.99 ± 0.02 | 1.26 ± 0.14 | 2.19 ± 0.11 | 110.30 ± 3.80 | 1.96 ± 0.09 |
| Spray-and-Wait (L=8) | 0.94 ± 0.04 | 0.96 ± 0.05 | 5.31 ± 1.04 | 2.09 ± 0.15 | 29.36 ± 1.52 | 0.51 ± 0.03 |
| PRoPHET (GRTR) | 1.00 ± 0.01 | 0.99 ± 0.02 | 1.65 ± 0.10 | 2.16 ± 0.10 | 91.91 ± 5.30 | 2.10 ± 0.10 |
| Direct delivery | 0.63 ± 0.08 | 0.72 ± 0.14 | 13.02 ± 3.29 | 1.00 ± 0.00 | 7.12 ± 0.91 | 0.10 ± 0.01 |
| MARL (full) | 0.92 ± 0.02 | 0.96 ± 0.04 | 4.65 ± 0.37 | 3.92 ± 0.19 | 24.79 ± 1.53 | 1.35 ± 0.06 |
| Epidemic, instant purge | 1.00 ± 0.00 | 0.99 ± 0.02 | 1.22 ± 0.14 | 2.21 ± 0.13 | 72.23 ± 4.12 | 1.27 ± 0.09 |
| Spray-and-Wait (L=8), instant purge | 0.94 ± 0.04 | 0.95 ± 0.07 | 5.45 ± 0.70 | 2.08 ± 0.09 | 24.81 ± 1.27 | 0.43 ± 0.03 |
| PRoPHET (GRTR), instant purge | 1.00 ± 0.00 | 0.99 ± 0.02 | 1.64 ± 0.08 | 2.15 ± 0.12 | 37.84 ± 3.87 | 1.13 ± 0.07 |

## 48 nodes

| Variant | PDR | SOS PDR | Latency (s) | Hops | Tx / delivered | Energy / delivered |
|---|---|---|---|---|---|---|
| Flooding (BitChat TTL=7) | 0.99 ± 0.01 | 0.99 ± 0.01 | 0.89 ± 0.04 | 2.22 ± 0.10 | 47.03 ± 0.18 | 13.54 ± 0.64 |
| Epidemic | 1.00 ± 0.00 | 1.00 ± 0.00 | 1.05 ± 0.02 | 2.10 ± 0.08 | 168.57 ± 1.32 | 2.94 ± 0.04 |
| Spray-and-Wait (L=8) | 0.93 ± 0.02 | 0.96 ± 0.02 | 5.36 ± 0.70 | 2.04 ± 0.04 | 29.03 ± 0.83 | 0.50 ± 0.01 |
| PRoPHET (GRTR) | 1.00 ± 0.00 | 1.00 ± 0.00 | 1.38 ± 0.05 | 2.11 ± 0.07 | 139.55 ± 3.28 | 3.12 ± 0.07 |
| Direct delivery | 0.62 ± 0.03 | 0.71 ± 0.06 | 11.44 ± 1.31 | 1.00 ± 0.00 | 6.64 ± 0.41 | 0.10 ± 0.00 |
| MARL (full) | 0.90 ± 0.01 | 0.92 ± 0.04 | 3.93 ± 0.15 | 4.28 ± 0.09 | 31.76 ± 0.95 | 1.88 ± 0.07 |
| Epidemic, instant purge | 1.00 ± 0.00 | 1.00 ± 0.00 | 1.04 ± 0.03 | 2.10 ± 0.08 | 105.40 ± 2.32 | 1.84 ± 0.03 |
| Spray-and-Wait (L=8), instant purge | 0.93 ± 0.02 | 0.96 ± 0.02 | 4.90 ± 0.37 | 2.05 ± 0.04 | 24.70 ± 0.57 | 0.42 ± 0.01 |
| PRoPHET (GRTR), instant purge | 1.00 ± 0.00 | 1.00 ± 0.00 | 1.36 ± 0.03 | 2.09 ± 0.06 | 52.07 ± 1.50 | 1.57 ± 0.04 |

## Sinkhole at t = 30 s (16 nodes, most central node)

| Variant | PDR after attack | Packets swallowed |
|---|---|---|
| Flooding (BitChat TTL=7) | 0.77 ± 0.08 | 0.00 ± 0.00 |
| Epidemic | 1.00 ± 0.02 | 2470.17 ± 622.30 |
| Spray-and-Wait (L=8) | 0.94 ± 0.02 | 123.33 ± 43.77 |
| PRoPHET (GRTR) | 1.00 ± 0.02 | 2465.08 ± 624.99 |
| Direct delivery | 0.65 ± 0.07 | 0.00 ± 0.00 |
| MARL (full) | 0.85 ± 0.04 | 17.42 ± 2.61 |
