#!/usr/bin/env python3
"""Weak-link QoS test: latency decomposition of QoS 2 vs QoS 0/1, radio round trips, and block-bootstrap CIs.

Reads <run>/weak_link/messages.csv written by analysis/weak_link_qos2.py (one row per message, with
the capture timestamps and components). Components per message (ms):
  A = Pi publish -> broker reply out: (a) Pi -> NIC + (r) broker turnaround (QoS 2); (a) only for
      QoS 0/1 (no reply before forwarding)
  B = (b) PUBREC out -> PUBREL in, the extra radio round trip (QoS 2 only; 0 for QoS 0/1)
  C = (c) broker -> logger (QoS 2: from PUBREL; QoS 0/1: from PUBLISH)
  A + B + C = end-to-end latency exactly, so means add up; medians and p95 do not, so the per-component
  differences of medians / p95 are shown next to the end-to-end difference, not as a split of it.
Radio round trip, clock-free: broker reply (PUBACK / PUBREC) out -> the Pi's first TCP ACK covering it
(rt_tcp), by median (QoS 1's tail is the Pi's delayed ACK).
CIs: analysis/bootstrap_ci.py's circular moving-block bootstrap (blocks of --block-s on the publish
time, circular within each contiguous stretch = segment), 10,000 resamples, seed 20261126 with a
per-cell stream, percentile 95% intervals; cells resampled independently, so differences of
resampled statistics give the interval of the difference.

The first run is the reference position: changes (b median/p95, QoS 2 - QoS 1 p95 gap) are each
later position minus it. --block-s takes a list (e.g. 2,1,5: the first is the main choice, the
others a sensitivity check); weak_link_ci.csv has a block_s column.

Usage: python analysis/weak_link_ci.py data/weak_link_p2m/r1 data/weak_link_wall1/r1 [...] [--block-s 2,1,5] [--out DIR]
Writes DIR/weak_link_decomposition.csv, weak_link_rt.csv, weak_link_ci.csv (default data/weak_link_summary/).
"""
import argparse, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import bootstrap_ci as BC  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("runs", nargs="+")
ap.add_argument("--block-s", default="2", help="block length(s) in s, comma-separated")
ap.add_argument("--resamples", type=int, default=10000)
ap.add_argument("--out", default=os.path.join(ROOT, "data", "weak_link_summary"))
a = ap.parse_args()

M = []
for run in a.runs:
    m = pd.read_csv(os.path.join(run, "weak_link", "messages.csv"))
    m = m[m.t_rx_ns.notna()].copy()
    q2 = m.qos == 2
    m["A"] = np.where(q2, m.a_ms + m.r_ms, m.a_ms)
    m["B"] = np.where(q2, m.b_ms, 0.0)
    m["C"] = m.c_ms
    m["t"] = m.t_pub_ns / 1e9
    M.append(m)
M = pd.concat(M, ignore_index=True)
pts = list(dict.fromkeys(M.point))
pc = lambda v, q: float(np.percentile(np.asarray(v, float)[~np.isnan(np.asarray(v, float))], q))

# ---------------------------------------------------------------- decomposition
rows = []
for pt in pts:
    g2 = M[(M.point == pt) & (M.qos == 2)]
    g2c = g2.dropna(subset=["A", "B", "C"])                  # complete handshakes only (all but 1 at wall1)
    for ref_name, refq in (("QoS 0", [0]), ("QoS 1", [1]), ("QoS 0+1", [0, 1])):
        r = M[(M.point == pt) & M.qos.isin(refq)].dropna(subset=["A", "C"])
        for comp, col in (("end-to-end", "latency_ms"), ("A: Pi -> NIC + broker turnaround", "A"),
                          ("B: PUBREC -> PUBREL radio round trip", "B"), ("C: broker -> logger", "C")):
            rows.append({"point": pt, "vs": ref_name, "component": comp,
                         "qos2_p50": pc(g2c[col], 50), "ref_p50": pc(r[col], 50), "d_p50": pc(g2c[col], 50) - pc(r[col], 50),
                         "qos2_p95": pc(g2c[col], 95), "ref_p95": pc(r[col], 95), "d_p95": pc(g2c[col], 95) - pc(r[col], 95),
                         "qos2_mean": g2c[col].mean(), "ref_mean": r[col].mean(),
                         "d_mean": g2c[col].mean() - r[col].mean()})
DEC = pd.DataFrame(rows)

RT = (M[M.qos > 0].groupby(["point", "qos"])
      .agg(rt_tcp_p50=("rt_tcp_ms", "median"), rt_tcp_p95=("rt_tcp_ms", lambda v: v.quantile(.95)), rt_tcp_gt30_pct=("rt_tcp_ms", lambda v: 100 * (v > 30).mean()),
           b_p50=("b_ms", "median"), b_p95=("b_ms", lambda v: v.quantile(.95)), n=("rt_tcp_ms", "count")).reset_index())

# ---------------------------------------------------------------- CIs
R = a.resamples
blocks = [float(x) for x in a.block_s.split(",")]


def boot(pt, qos, col, qs, B):
    g = M[(M.point == pt) & (M.qos == qos)].dropna(subset=[col])
    exc, Q = BC.boot_cell(g.t.values, g[col].values, B, R, BC.rng_for("weak_link", pt, qos, col, B), qs=qs)
    return g, 100 * exc / len(g), Q


def row(B, name, est, dist, ga=None, gb=None):
    lo, hi = BC.ci(dist)
    return {"block_s": B, "comparison": name, "estimate": est, "lo": lo, "hi": hi,
            "n_a / n_b": f"{len(ga)} / {len(gb)}" if ga is not None else "",
            "blocks_a / b": f"{BC.n_blocks(ga.t, B)} / {BC.n_blocks(gb.t, B)}" if ga is not None else "",
            "verdict": BC.verdict(lo, hi)}


ci = []
for B in blocks:
    lat, gap, bq = {}, {}, {}
    for pt in pts:
        for q in (0, 1, 2):
            lat[pt, q] = boot(pt, q, "latency_ms", (95,), B)
        g2, s2, Q2 = lat[pt, 2]
        for ref in (1, 0):
            gr, sr, Qr = lat[pt, ref]
            ci.append(row(B, f"{pt}: p95 latency, QoS 2 - QoS {ref} (ms)",
                          pc(g2.latency_ms, 95) - pc(gr.latency_ms, 95), Q2[0] - Qr[0], g2, gr))
            ci.append(row(B, f"{pt}: share > 20 ms, QoS 2 - QoS {ref} (pp)",
                          100 * (g2.latency_ms > 20).mean() - 100 * (gr.latency_ms > 20).mean(), s2 - sr, g2, gr))
        g1, _, Q1 = lat[pt, 1]
        gap[pt] = (pc(g2.latency_ms, 95) - pc(g1.latency_ms, 95), Q2[0] - Q1[0])
        bq[pt] = boot(pt, 2, "b_ms", (50, 95), B)
    p0 = pts[0]
    for p1 in pts[1:]:
        gA, _, QA = bq[p1]
        gB, _, QB = bq[p0]
        for k, (name, q) in enumerate((("median", 50), ("p95", 95))):
            ci.append(row(B, f"(b) PUBREC -> PUBREL {name}, {p1} - {p0} (ms)",
                          pc(gA.b_ms, q) - pc(gB.b_ms, q), QA[k] - QB[k], gA, gB))
        # interaction: does the QoS 2 - QoS 1 p95 gap grow at this position? (independent cells)
        ci.append(row(B, f"p95 gap (QoS 2 - QoS 1), {p1} - {p0} (ms)",
                      gap[p1][0] - gap[p0][0], gap[p1][1] - gap[p0][1]))
CI = pd.DataFrame(ci)

os.makedirs(a.out, exist_ok=True)
DEC.to_csv(os.path.join(a.out, "weak_link_decomposition.csv"), index=False)
RT.to_csv(os.path.join(a.out, "weak_link_rt.csv"), index=False)
CI.to_csv(os.path.join(a.out, "weak_link_ci.csv"), index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 20)
print(DEC.round(2).to_string(index=False)); print(); print(RT.round(2).to_string(index=False)); print()
print(f"CIs: blocks {blocks} s, {R} resamples, seed {BC.SEED}"); print(CI.round(3).to_string(index=False))
