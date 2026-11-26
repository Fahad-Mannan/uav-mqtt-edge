#!/usr/bin/env python3
"""Synthetic check of flight_state.detect_hovers and lean (no log needed).
Track at 10 Hz: takeoff over home, out to 50.3 m, hover 100 s (with 0.3 m wander), move, hover 100 s at
153.4 m with a gust that drifts 3 m for 4 s, back. Run: python tests/test_flight_state.py"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "analysis"))
import flight_state as FS

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name} {detail}")

rng = np.random.default_rng(1)
seg = [("climb", 30, 0, 0), ("out", 15, 0, 50.3), ("hover", 100, 50.3, 50.3), ("out", 30, 50.3, 153.4),
       ("hover", 100, 153.4, 153.4), ("back", 40, 153.4, 0)]
t, d = [], []
t0 = 1000.0
for name, dur, a, b in seg:
    n = int(dur * 10)
    t += list(t0 + np.arange(n) / 10)
    d += list(np.linspace(a, b, n))
    t0 += dur
t, d = np.array(t), np.array(d)
hov = np.abs(np.diff(np.r_[d[0], d])) < 1e-9
d = d + np.where(hov, 0.3 * np.sin(t / 7) + rng.normal(0, 0.05, len(d)), 0)   # wander while hovering
gust = (t > 1000 + 30 + 15 + 100 + 30 + 40) & (t < 1000 + 30 + 15 + 100 + 30 + 44)
d[gust] += np.linspace(0, 3, gust.sum())
alt = np.where(t < 1030, (t - 1000) / 2, 15.0)
tr = pd.DataFrame({"utc": t, "north_m": d, "east_m": 0.0, "dist_m": d, "alt_m": alt})
dt = np.gradient(t)
tr["speed_ms"] = pd.Series(np.abs(np.gradient(d) / dt)).rolling(10, center=True, min_periods=1).mean().values

hv = FS.detect_hovers(tr, min_alt=12)
check("two hovers detected", len(hv) == 2, str([h["dist_m"] for h in hv]))
if len(hv) == 2:
    check("distances 50.3 and 153.4 (+-0.3)", abs(hv[0]["dist_m"] - 50.3) < 0.3 and abs(hv[1]["dist_m"] - 153.4) < 0.3)
    # the +-2 m window also takes the last/first ~0.6 s of the approach and departure (3.4 m/s)
    check("hover 1 window ~100 s", 95 <= hv[0]["dur_s"] <= 103, f"{hv[0]['dur_s']:.1f} s")
    check("gust of 3 m splits the +-2 m window of hover 2 (longest piece kept)", hv[1]["dur_s"] < 100,
          f"{hv[1]['dur_s']:.1f} s")
check("min_hover_s 150 finds none", FS.detect_hovers(tr, min_alt=12, min_hover_s=150) == [])

# lean: roll 0, pitch -5 deg (nose down) at yaw 90 (east) -> thrust tilts toward east (90 deg)
att = pd.DataFrame({"Roll": [0.0] * 10, "Pitch": [-5.0] * 10, "Yaw": [90.0] * 10})
tilt, mean_tilt, toward = FS.lean(att)
check("lean 5 deg", abs(tilt.mean() - 5) < 0.01 and abs(mean_tilt - 5) < 0.01, f"{tilt.mean():.2f}")
check("toward 90 deg (nose-down while facing east)", abs(toward - 90) < 0.5, f"{toward:.1f}")
# roll right (+10) at yaw 0 -> thrust tilts toward east
tilt, mean_tilt, toward = FS.lean(pd.DataFrame({"Roll": [10.0], "Pitch": [0.0], "Yaw": [0.0]}))
check("roll right at yaw 0 -> toward 90 deg", abs(toward - 90) < 0.5, f"{toward:.1f}")
print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
