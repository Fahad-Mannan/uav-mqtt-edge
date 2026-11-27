# Comparisons, % > 20 ms differences in percentage points (2 s blocks)

Moving-block bootstrap, 10000 resamples, seed 20261126, percentile 95% intervals; blocks of 1, 2, 5 s (primary 2 s). First-arrival latency per unique message, same selection as link_bands.py / metrics.py (point estimates checked against the published tables). Bands: > -55, (-65, -55], (-75, -65], <= -75 dBm. Too small: n < 100 or blocks < 10. A share of 0 events gives a degenerate [0, 0] interval: the bootstrap cannot bound it from above.

| part | flight | comparison | ref band | n a / b | a % | b % | diff pp [95% CI] | verdict |
|---|---|---|---|---|---|---|---|---|
| a | F1 | QoS2 - QoS1, -65 to -75 |  | 581 / 830 | 2.24 | 1.93 | 0.31 [-2.63, 2.65] | includes 0: inconclusive |
| a | F1 | QoS2 - QoS0, -65 to -75 |  | 581 / 612 | 2.24 | 1.47 | 0.77 [-3.83, 3.44] | includes 0: inconclusive |
| b | F1 | QoS2: -65 to -75 minus strongest band | -55 to -65 | 581 / 831 | 2.24 | 0.0 | 2.24 [1.03, 3.79] | excludes 0 (> 0) |
| a | F2 | QoS2 - QoS1, -65 to -75 |  | 525 / 697 | 6.29 | 0.57 | 5.71 [3.14, 8.38] | excludes 0 (> 0) |
| a | F2 | QoS2 - QoS0, -65 to -75 |  | 525 / 725 | 6.29 | 0.83 | 5.46 [2.84, 8.16] | excludes 0 (> 0) |
| b | F2 | QoS2: -65 to -75 minus strongest band | -55 to -65 | 525 / 720 | 6.29 | 0.0 | 6.29 [3.81, 8.95] | excludes 0 (> 0) |
| a | F3 | QoS2 - QoS1, -65 to -75 |  | 1017 / 885 | 1.18 | 0.23 | 0.95 [0.14, 1.84] | excludes 0 (> 0) |
| a | F3 | QoS2 - QoS0, -65 to -75 |  | 1017 / 693 | 1.18 | 0.0 | 1.18 [0.49, 1.97] | excludes 0 (> 0) |
| b | F3 | QoS2: -65 to -75 minus strongest band | -55 to -65 | 1017 / 423 | 1.18 | 0.24 | 0.94 [0.12, 1.83] | excludes 0 (> 0) |
| a | F4 | QoS2 - QoS1, -65 to -75 |  | 870 / 627 | 3.22 | 0.16 | 3.06 [0.14, 8.69] | excludes 0 (> 0) |
| a | F4 | QoS2 - QoS0, -65 to -75 |  | 870 / 1069 | 3.22 | 0.09 | 3.12 [0.25, 8.76] | excludes 0 (> 0) |
| b | F4 | QoS2: -65 to -75 minus strongest band | -55 to -65 | 870 / 725 | 3.22 | 1.1 | 2.11 [-1.17, 7.89] | includes 0: inconclusive |
| c | pooled | QoS2 - QoS1, -65 to -75 |  | 2993 / 3039 | 2.87 | 0.76 | 2.12 [0.79, 3.98] | excludes 0 (> 0) |
| c | pooled | QoS2 - QoS0, -65 to -75 |  | 2993 / 3099 | 2.87 | 0.52 | 2.36 [0.93, 4.22] | excludes 0 (> 0) |
| c | pooled | QoS2: -65 to -75 minus strongest band | F1:-55 to -65+F2:-55 to -65+F3:-55 to -65+F4:-55 to -65 | 2993 / 2699 | 2.87 | 0.33 | 2.54 [1.39, 4.32] | excludes 0 (> 0) |
