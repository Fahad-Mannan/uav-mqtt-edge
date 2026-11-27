# Bench base_final (Table 3)

Moving-block bootstrap, 10000 resamples, seed 20261126, percentile 95% intervals; blocks of 1, 2, 5 s (primary 2 s). First-arrival latency per unique message, same selection as link_bands.py / metrics.py (point estimates checked against the published tables). Bands: > -55, (-65, -55], (-75, -65], <= -75 dBm. Too small: n < 100 or blocks < 10. A share of 0 events gives a degenerate [0, 0] interval: the bootstrap cannot bound it from above.

| QoS | scans | method | n | units | p95 ms [95% CI] | p99 ms [95% CI] | > 20 ms % [95% CI] | note |
|---|---|---|---|---|---|---|---|---|
| 0 | with | runs (5) | 7200 | 5 | 6.11 [6.03, 6.17] | 7.44 [6.46, 65.40] | 0.750 [0.000, 2.250] | 126 distinct run multisets |
| 0 | with | blocks 1 s | 7200 | 304 | 6.11 [6.05, 6.17] | 7.44 [6.50, 53.10] | 0.750 [0.139, 1.556] | stratified by run |
| 0 | with | blocks 2 s | 7200 | 154 | 6.11 [6.05, 6.18] | 7.44 [6.46, 55.35] | 0.750 [0.000, 1.847] | stratified by run |
| 0 | with | blocks 5 s | 7200 | 65 | 6.11 [6.04, 6.22] | 7.44 [6.43, 65.37] | 0.750 [0.000, 2.194] | stratified by run |
| 0 | without | runs (5) | 7064 | 5 | 6.07 [5.96, 6.13] | 6.49 [6.38, 6.60] | 0.000 [0.000, 0.000] | 126 distinct run multisets |
| 0 | without | blocks 1 s | 7064 | 299 | 6.07 [6.04, 6.10] | 6.49 [6.40, 6.61] | 0.000 [0.000, 0.000] | stratified by run |
| 0 | without | blocks 2 s | 7064 | 152 | 6.07 [6.03, 6.10] | 6.49 [6.39, 6.64] | 0.000 [0.000, 0.000] | stratified by run |
| 0 | without | blocks 5 s | 7064 | 65 | 6.07 [6.01, 6.11] | 6.49 [6.38, 6.66] | 0.000 [0.000, 0.000] | stratified by run |
| 1 | with | runs (5) | 7200 | 5 | 6.13 [5.96, 6.38] | 40.70 [6.38, 76.64] | 1.431 [0.000, 2.903] | 126 distinct run multisets |
| 1 | with | blocks 1 s | 7200 | 305 | 6.13 [6.06, 6.24] | 40.70 [6.86, 71.50] | 1.431 [0.569, 2.444] | stratified by run |
| 1 | with | blocks 2 s | 7200 | 155 | 6.13 [6.05, 6.30] | 40.70 [6.61, 76.41] | 1.431 [0.333, 2.834] | stratified by run |
| 1 | with | blocks 5 s | 7200 | 65 | 6.13 [6.03, 6.39] | 40.70 [6.48, 81.09] | 1.431 [0.014, 3.222] | stratified by run |
| 1 | without | runs (5) | 6925 | 5 | 6.05 [5.91, 6.12] | 6.46 [6.28, 6.60] | 0.000 [0.000, 0.000] | 126 distinct run multisets |
| 1 | without | blocks 1 s | 6925 | 297 | 6.05 [6.02, 6.09] | 6.46 [6.35, 6.56] | 0.000 [0.000, 0.000] | stratified by run |
| 1 | without | blocks 2 s | 6925 | 152 | 6.05 [6.01, 6.09] | 6.46 [6.33, 6.57] | 0.000 [0.000, 0.000] | stratified by run |
| 1 | without | blocks 5 s | 6925 | 65 | 6.05 [6.00, 6.10] | 6.46 [6.32, 6.59] | 0.000 [0.000, 0.000] | stratified by run |
| 2 | with | runs (5) | 7200 | 5 | 8.76 [8.46, 9.13] | 10.99 [9.33, 71.63] | 0.819 [0.000, 2.458] | 126 distinct run multisets |
| 2 | with | blocks 1 s | 7200 | 304 | 8.76 [8.62, 8.91] | 10.99 [9.58, 53.95] | 0.819 [0.153, 1.708] | stratified by run |
| 2 | with | blocks 2 s | 7200 | 154 | 8.76 [8.60, 8.97] | 10.99 [9.49, 58.86] | 0.819 [0.000, 1.972] | stratified by run |
| 2 | with | blocks 5 s | 7200 | 65 | 8.76 [8.57, 9.04] | 10.99 [9.41, 71.59] | 0.819 [0.000, 2.347] | stratified by run |
| 2 | without | runs (5) | 7061 | 5 | 8.67 [8.47, 8.81] | 9.51 [9.30, 9.64] | 0.000 [0.000, 0.000] | 126 distinct run multisets |
| 2 | without | blocks 1 s | 7061 | 299 | 8.67 [8.56, 8.76] | 9.51 [9.35, 9.72] | 0.000 [0.000, 0.000] | stratified by run |
| 2 | without | blocks 2 s | 7061 | 152 | 8.67 [8.55, 8.77] | 9.51 [9.33, 9.74] | 0.000 [0.000, 0.000] | stratified by run |
| 2 | without | blocks 5 s | 7061 | 65 | 8.67 [8.53, 8.79] | 9.51 [9.31, 9.79] | 0.000 [0.000, 0.000] | stratified by run |
