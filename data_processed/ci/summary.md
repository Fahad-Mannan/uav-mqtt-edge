# Bootstrap 95% CIs: summary (2026-11-26, `analysis/bootstrap_ci.py`)

Method: moving-block bootstrap, circular within each contiguous stretch of a cell (no gap > 1 s),
10,000 resamples, seed 20261126, percentile intervals; blocks 2 s (primary), 1 s and 5 s as a
sensitivity check. First-arrival latency per unique message, same selection as `link_bands.py` /
`metrics.py`; every point estimate reproduces `link_bands_per_flight.csv` and
`base_final/metrics_pooled.csv` exactly. The plain (non-circular) moving-block version was tried first
and rejected: late messages cluster at stretch ends (band transitions), which plain blocks
under-sample (bootstrap mean down to 0.25 x the observed share); the circular version is unbiased
(0.96-1.03 x in every cell at every block length). Tables: `flight_bands_ci.md`, `comparisons_ci.md`,
`bench_base_final_ci.md`, `sensitivity_blocks.md` (CSV alongside).

**Supported (interval excludes 0 at 1, 2 and 5 s):** QoS 2 is more link-sensitive when pooled over the
four flights. In the -65 to -75 dBm band its share > 20 ms exceeds QoS 1's by 2.12 pp [0.79, 3.98] and
QoS 0's by 2.36 pp [0.93, 4.22]. QoS 2's share in that band exceeds its share in the -55 to -65 band by
2.54 pp [1.39, 4.32]. Per flight this holds in F2 (all three comparisons, +5.5 to +6.3 pp), for F3
QoS 2 - QoS 0 and for F1's band effect.

**Fragile (excludes 0 at 1 and 2 s, not at 5 s):** F3 QoS 2 - QoS 1, F3's band effect, and F4 QoS 2 vs
QoS 0/1. The F4 intervals are wide (2 s: [0.14, 8.69]) because its QoS 2 tail is a few clusters.

**Inconclusive at every block length:** F1 QoS 2 vs QoS 0/1 within -65 to -75 (+0.3 and +0.8 pp,
intervals about [-3, +3]) and F4's band effect (+2.1 pp [-1.17, 7.89]).

**Too small:** every > -55 cell, every <= -75 cell (including F2 QoS 2's 23.1% [19.0, 27.2], which
rests on 195 messages in 8 blocks), and at 5 s blocks many more cells fall below 10 blocks.

**Bench (base_final):** without scan windows every QoS has p95 within about ±0.15 ms and p99 within
about ±0.2 ms. The share > 20 ms is 0 of about 7,000 messages; the bootstrap gives a degenerate
[0, 0] there, so it cannot bound the share from above. With scans the tail is undetermined: QoS 1 p99
40.7 ms [6.6, 76.4] (two scans), and the QoS 0/2 share > 20 ms intervals include 0 at 2 and 5 s. The
run-level bootstrap (5 runs, 126 distinct multisets) gives similar or wider intervals and is coarse.

**Block length:** conclusions do not change between 1 and 2 s. At 5 s intervals widen, mostly for the
F4 cells, and the four "fragile" comparisons above cross 0; the pooled results and F2 do not change.
Flight-cell medians are tight (typically ±0.1-0.5 ms) except F4 QoS 0 at -65 to -75 (9.96 ms
[9.38, 12.85]), which spans the unexplained ~4 ms step from s09.
