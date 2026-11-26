#!/usr/bin/env python3
"""Summarize one logger CSV: per-topic delivery and latency statistics."""
import glob, os, sys
import pandas as pd

if len(sys.argv) > 1:
    path = sys.argv[1]
else:
    path = max(glob.glob(os.path.expanduser("~/uav-mqtt/data/run_*.csv")),
               key=os.path.getmtime)
df = pd.read_csv(path)

def stats(g):
    lat = g["latency_ms"].dropna()
    expected = int(g["seq"].max()) + 1
    return {
        "received": len(g),
        "expected": expected,
        "loss_pct": 100 * (1 - g["seq"].nunique() / expected),
        "dups": int(g["dup"].sum()),
        "mean_ms": lat.mean(),
        "p50_ms": lat.median(),
        "p95_ms": lat.quantile(0.95),
        "p99_ms": lat.quantile(0.99),
        "max_ms": lat.max(),
        "jitter_sd_ms": lat.std(),
    }

res = pd.DataFrame({t: stats(g) for t, g in df.groupby("topic")}).T.round(2)
print(path)
print(res.to_string())
dur = (df["t_rx_ns"].max() - df["t_rx_ns"].min()) / 1e9
kbps = df["bytes"].sum() * 8 / dur / 1000
print(f"\nDuration {dur:.1f} s | {len(df)} messages | payload rate {kbps:.1f} kbps (MQTT payload only)")
