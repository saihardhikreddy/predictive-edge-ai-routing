# Link-survival prediction

6 seeds per cell, 300 s per run. Target: the neighbour is still heard at every beacon for the next 3 s.
Scored test-then-train after a 60 s warm-up; pooled over all nodes and seeds. AUC = chance a surviving link is ranked
above a breaking one (0.5 = guessing). Brier = mean squared error of the probability (lower is better).

## A. Prediction quality (16 nodes)

| Mobility | Links that break | Model | AUC | Brier | Log loss | Breaks flagged (recall) | Precision |
|---|---|---|---|---|---|---|---|
| x1 | 2.2 % | Trend (RSSI + slope + age) | 0.547 | 0.0214 | 0.107 | 0 % | 0 % |
| x1 | 2.2 % | RSSI only | 0.516 | 0.0215 | 0.109 | 0 % | 0 % |
| x1 | 2.2 % | Base rate | 0.526 | 0.0213 | 0.106 | 0 % | 0 % |
| x1 | 2.2 % | Always survives | 0.500 | 0.0217 | 0.300 | 0 % | 0 % |
| x2 | 4.2 % | Trend (RSSI + slope + age) | 0.718 | 0.0396 | 0.165 | 0 % | 7 % |
| x2 | 4.2 % | RSSI only | 0.686 | 0.0398 | 0.168 | 0 % | 0 % |
| x2 | 4.2 % | Base rate | 0.514 | 0.0406 | 0.176 | 0 % | 0 % |
| x2 | 4.2 % | Always survives | 0.500 | 0.0423 | 0.585 | 0 % | 0 % |
| x4 | 8.5 % | Trend (RSSI + slope + age) | 0.850 | 0.0691 | 0.238 | 4 % | 27 % |
| x4 | 8.5 % | RSSI only | 0.748 | 0.0743 | 0.266 | 0 % | 4 % |
| x4 | 8.5 % | Base rate | 0.513 | 0.0782 | 0.292 | 0 % | 0 % |
| x4 | 8.5 % | Always survives | 0.500 | 0.0854 | 1.180 | 0 % | 0 % |
| x8 | 17.8 % | Trend (RSSI + slope + age) | 0.832 | 0.1159 | 0.361 | 29 % | 57 % |
| x8 | 17.8 % | RSSI only | 0.700 | 0.1379 | 0.431 | 3 % | 34 % |
| x8 | 17.8 % | Base rate | 0.508 | 0.1469 | 0.470 | 0 % | 0 % |
| x8 | 17.8 % | Always survives | 0.500 | 0.1784 | 2.464 | 0 % | 0 % |

Calibration of the trend model at x4 (mean predicted vs observed survival, count):

| Predicted | Observed | Count |
|---|---|---|
| 0.16 | 0.96 | 70 |
| 0.32 | 0.80 | 555 |
| 0.52 | 0.64 | 2458 |
| 0.73 | 0.69 | 13929 |
| 0.93 | 0.95 | 108840 |

## B. Routing with and without prediction

| Nodes | Mobility | Router | PDR | Latency (s) | Link failures | Energy / delivered |
|---|---|---|---|---|---|---|
| 16 | x1 | Learned routing | 0.887 ± 0.048 | 7.288 ± 2.625 | 147.333 ± 39.606 | 0.813 ± 0.061 |
| 16 | x1 | + prediction (3-s discount) | 0.881 ± 0.038 | 7.857 ± 3.036 | 140.833 ± 50.681 | 0.813 ± 0.049 |
| 16 | x1 | + prediction (per-hop discount) | 0.891 ± 0.058 | 8.049 ± 1.962 | 141.833 ± 15.817 | 0.808 ± 0.051 |
| 16 | x1 | + prediction (last-chance handoff) | 0.887 ± 0.048 | 7.288 ± 2.625 | 147.333 ± 39.606 | 0.813 ± 0.061 |
| 16 | x4 | Learned routing | 0.950 ± 0.014 | 8.780 ± 1.014 | 96.000 ± 12.617 | 0.956 ± 0.021 |
| 16 | x4 | + prediction (3-s discount) | 0.927 ± 0.012 | 10.092 ± 0.920 | 95.500 ± 16.233 | 0.983 ± 0.022 |
| 16 | x4 | + prediction (per-hop discount) | 0.940 ± 0.013 | 9.120 ± 1.577 | 107.667 ± 21.768 | 0.967 ± 0.035 |
| 16 | x4 | + prediction (last-chance handoff) | 0.940 ± 0.013 | 8.747 ± 0.969 | 96.667 ± 13.995 | 0.969 ± 0.032 |
| 16 | x8 | Learned routing | 0.962 ± 0.014 | 7.899 ± 0.734 | 91.333 ± 23.347 | 1.116 ± 0.014 |
| 16 | x8 | + prediction (3-s discount) | 0.944 ± 0.023 | 9.054 ± 0.495 | 70.333 ± 14.528 | 1.137 ± 0.052 |
| 16 | x8 | + prediction (per-hop discount) | 0.954 ± 0.022 | 8.166 ± 0.968 | 80.667 ± 12.258 | 1.127 ± 0.041 |
| 16 | x8 | + prediction (last-chance handoff) | 0.966 ± 0.009 | 7.918 ± 0.609 | 93.500 ± 15.783 | 1.117 ± 0.017 |
| 32 | x1 | Learned routing | 0.924 ± 0.023 | 4.651 ± 0.370 | 201.333 ± 24.279 | 1.347 ± 0.057 |
| 32 | x1 | + prediction (3-s discount) | 0.932 ± 0.027 | 5.310 ± 0.754 | 205.833 ± 14.470 | 1.332 ± 0.055 |
| 32 | x1 | + prediction (per-hop discount) | 0.929 ± 0.024 | 4.473 ± 0.525 | 188.500 ± 8.712 | 1.332 ± 0.050 |
| 32 | x1 | + prediction (last-chance handoff) | 0.924 ± 0.023 | 4.651 ± 0.370 | 201.333 ± 24.279 | 1.347 ± 0.057 |
| 32 | x4 | Learned routing | 0.879 ± 0.015 | 3.822 ± 0.412 | 127.833 ± 15.791 | 1.810 ± 0.053 |
| 32 | x4 | + prediction (3-s discount) | 0.866 ± 0.022 | 5.206 ± 0.569 | 133.500 ± 16.885 | 1.861 ± 0.055 |
| 32 | x4 | + prediction (per-hop discount) | 0.881 ± 0.025 | 4.315 ± 0.313 | 129.667 ± 20.559 | 1.813 ± 0.060 |
| 32 | x4 | + prediction (last-chance handoff) | 0.887 ± 0.021 | 3.924 ± 0.292 | 136.500 ± 16.368 | 1.794 ± 0.053 |
| 32 | x8 | Learned routing | 0.843 ± 0.021 | 4.649 ± 0.466 | 132.500 ± 8.826 | 2.348 ± 0.077 |
| 32 | x8 | + prediction (3-s discount) | 0.854 ± 0.026 | 6.077 ± 0.762 | 111.500 ± 15.959 | 2.319 ± 0.079 |
| 32 | x8 | + prediction (per-hop discount) | 0.838 ± 0.022 | 4.870 ± 0.787 | 129.333 ± 21.116 | 2.361 ± 0.085 |
| 32 | x8 | + prediction (last-chance handoff) | 0.845 ± 0.027 | 4.650 ± 0.698 | 137.167 ± 16.437 | 2.340 ± 0.075 |
