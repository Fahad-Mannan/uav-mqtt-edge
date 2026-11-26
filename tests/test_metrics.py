#!/usr/bin/env python3
"""Synthetic checks of the AoI computation in analysis/metrics.py.
Run: python tests/test_metrics.py"""
import importlib.util, os, sys
import numpy as np

spec = importlib.util.spec_from_file_location(
    "metrics", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "analysis", "metrics.py"))
src = open(spec.origin).read().split("\nfor name in sys.argv[1:]:")[0]   # definitions only
ns = {}
exec(compile(src, spec.origin, "exec"), ns)
aoi = ns["aoi"]

fails = 0
def check(name, got, want, tol=1e-6):
    global fails
    ok = abs(got - want) <= tol
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got:.6f}, want {want:.6f}")

ms = 1_000_000
T, d, n = 50, 3, 2000                       # period 50 ms, constant delay 3 ms
s = np.arange(n) * T * ms
avg, peaks = aoi(s, s + d * ms)
check("periodic, constant delay: average = T/2 + d", avg, T / 2 + d)
check("periodic, constant delay: peak = T + d", peaks.mean(), T + d)

# one update lost: the age keeps growing over 2T
r = s + d * ms
keep = np.ones(n, bool); keep[1000] = False
avg2, peaks2 = aoi(s[keep], r[keep])
check("one loss: max peak = 2T + d", peaks2.max(), 2 * T + d)
want = ((n - 3) * (T * (T / 2 + d)) + 2 * T * (T + d)) / ((n - 1) * T)
check("one loss: average", avg2, want)

# out-of-order arrival: an older sample arriving later must not reset the age
r3 = r.copy(); r3[500] = r[502] + 1 * ms   # sample 500 arrives after 502
avg3, peaks3 = aoi(s, r3)
check("reordered: stale sample ignored (max peak = 2T + d)", peaks3.max(), 2 * T + d)
sys.exit(1 if fails else 0)
