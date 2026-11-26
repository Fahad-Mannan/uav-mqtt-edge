#!/usr/bin/env python3
"""Aggregate a campaign folder: per-run table, then per-QoS summary with 95% CI."""
import glob, json, os, re, sys
import numpy as np, pandas as pd
from scipy import stats

name = sys.argv[1]
base = os.path.expanduser(f"~/uav-mqtt/data/{name}")

def grab(path, pat):
    try:
        m = re.search(pat, open(path).read())
        return float(m.group(1)) if m else np.nan
    except OSError:
        return np.nan

rows, pooled = [], {}
for rdir in sorted(glob.glob(f"{base}/qos*_rep*")):
    meta = json.load(open(f"{rdir}/meta.json"))
    df = pd.read_csv(f"{rdir}/rx.csv")
    sent = sum(1 for _ in open(f"{rdir}/pi_log.csv")) - 1
    got = len(df.drop_duplicates(["topic", "seq"]))
    lat = df["latency_ms"].dropna()
    pooled.setdefault(meta["qos"], []).append(lat.values)
    rows.append({
        "run": os.path.basename(rdir), "qos": meta["qos"], "sent": sent, "got": got,
        "loss_pct": 100 * (1 - got / sent), "mean_ms": lat.mean(), "p50_ms": lat.median(),
        "p95_ms": lat.quantile(0.95), "p99_ms": lat.quantile(0.99), "max_ms": lat.max(),
        "sig_dbm": grab(f"{rdir}/wifi_after.txt", r"signal:\s*(-?\d+)"),
        "tx_mbps": grab(f"{rdir}/wifi_after.txt", r"tx bitrate:\s*([\d.]+)"),
        "clk_rms_ms": 1000 * grab(f"{rdir}/chrony_after.txt", r"RMS offset\s*:\s*([\d.]+)"),
    })
runs = pd.DataFrame(rows)
print(runs.round(2).to_string(index=False))

print("\nPer-QoS summary: mean of run means +/- 95% CI over repeats; pooled percentiles")
for q, g in runs.groupby("qos"):
    x = g["mean_ms"].values
    ci = stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else float("nan")
    allv = np.concatenate(pooled[q])
    print(f"QoS {q}: runs={len(x)} mean={x.mean():.2f} +/- {ci:.2f} ms | "
          f"p50={np.percentile(allv, 50):.2f} p95={np.percentile(allv, 95):.2f} "
          f"p99={np.percentile(allv, 99):.2f} | loss={g['loss_pct'].mean():.3f}%")
runs.to_csv(f"{base}/summary_runs.csv", index=False)
