#!/usr/bin/env python3
"""95% confidence intervals for the paper's key latency statistics (moving-block bootstrap).

Existing data only (no Pi, no network). Reads data_processed/ (or $UAV_MQTT_DATA, as
make_figures.py) and writes data_processed/ci/ (or --out).

Messages: first-arrival latency per unique message, exactly as in the existing tables:
  - flights: position/msgs_pos.csv (flight_position.py, one row per sent message, first arrival),
    with link_bands.py's selection imported from that module: hover + transit bins only, messages
    published within 1 s of a Wi-Fi scan (scans.csv) left out, RSSI = nearest station-dump sample
    (rssi.csv) within 1.5 s, bands > -55, (-65, -55], (-75, -65], <= -75 dBm;
  - bench: base_final per run as in metrics.py (not imported): rx.csv sorted by arrival and deduplicated keep-first
    by topic/seq (every sent message was received, PDR 100%), scan windows from scans.csv (+-1 s).
  The point estimates are checked against link_bands/link_bands_per_flight.csv and
  base_final/metrics_pooled.csv (printed; the script stops if they disagree).

Moving-block bootstrap on the time axis, within each cell (flight x QoS x band, or run):
  - candidate blocks: one per message of the cell, = all the cell's messages published in
    [t_i, t_i + B) (overlapping, so "moving"); a cell is not contiguous in time (segments interleave
    QoS, the RSSI band changes), so a block never spans messages of other cells. Circular within each
    contiguous stretch of the cell (no gap > 1 s): a block running past the stretch end wraps to its
    start, so every message is equally likely to be drawn (the plain version under-weighted stretch
    ends, where late messages cluster; see mbb_indices);
  - a resample concatenates randomly drawn blocks until it holds exactly n messages (the last block
    truncated), as in the standard MBB;
  - "blocks" reported = number of occupied non-overlapping B-second windows (the effective number
    of independent time units); a cell with n < 100 or blocks < 10 is flagged too small;
  - B = 1, 2 (primary) and 5 s; 10,000 resamples; seed 20261126, combined with a stable hash of the
    cell name so every cell has its own independent stream; percentile intervals (2.5, 97.5);
  - quantiles: linear interpolation (numpy default = pandas default, as in the tables).
Differences: cells are resampled independently, so a difference of two cells' resampled statistics
is the bootstrap distribution of the difference. Pooled over flights: stratified by flight (each
flight's cell resampled on its own, then exceedances and counts summed).
Bench run-level bootstrap: 5 runs per QoS drawn with replacement, messages pooled.

Usage: python analysis/bootstrap_ci.py [--resamples 10000] [--blocks 1,2,5] [--out data_processed/ci]
(about 2.5 min with the defaults)
"""
import argparse, glob, os, re, sys, zlib
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
D = os.environ.get("UAV_MQTT_DATA", os.path.join(ROOT, "data_processed"))
sys.path.insert(0, HERE)
import link_bands as LB  # noqa: E402
# not imported from metrics.py: that module runs its campaign loop over sys.argv at import time
SCAN_MARGIN_S = 1.0      # = metrics.SCAN_MARGIN_S: drop messages within 1 s of a scan

SEED = 20261126
THR = 20.0
MIN_N, MIN_BLOCKS = 100, 10
PRIMARY_B = 2.0
FLIGHTS = [("F1", "f1b", "field_2026-11-22/f1b"), ("F2", "f2b", "field_2026-11-23/f2b"),
           ("F3", "f3", "field_2026-11-24/f3"), ("F4", "f4", "field_2026-11-24/f4")]
# link_bands names -> names used in the paper text (same intervals)
BAND_NAME = {"> -55": "> -55", "-65 to -55": "-55 to -65", "-75 to -65": "-65 to -75", "<= -75": "<= -75"}
BANDS = [b[2] for b in LB.BANDS]          # strongest first


def rng_for(*key):
    return np.random.default_rng([SEED, zlib.crc32("|".join(map(str, key)).encode())])


# ---------------------------------------------------------------- data
def read_scans(folder):
    """Completed Wi-Fi scans (start, end) from <folder>/scans.csv (the Pi's iw event log, processed)."""
    p = os.path.join(folder, "scans.csv")
    if not os.path.exists(p):
        return []
    s = pd.read_csv(p)
    return list(zip(s.start_unix.values, s.end_unix.values))


def read_station(folder):
    """Station-dump series <folder>/rssi.csv -> t, signal (rows with a signal, sorted), as LB.station."""
    s = pd.read_csv(os.path.join(folder, "rssi.csv")).rename(columns={"t_unix": "t", "signal_dbm": "signal"})
    return s.dropna(subset=["signal"]).sort_values("t").reset_index(drop=True)


def flight_msgs(path, max_gap_s=1.5):
    """link_bands.py's per-flight selection (same rules), from the processed files."""
    m = pd.read_csv(os.path.join(path, "position", "msgs_pos.csv"))
    sd = read_station(path)
    sc = read_scans(path)
    m = m[m.bin.str.startswith("hover") | (m.bin == "transit")].copy()
    in_scan = np.zeros(len(m), bool)
    for s0, s1 in sc:
        in_scan |= (m.t_pub.values >= s0 - 1) & (m.t_pub.values <= s1 + 1)
    i = np.searchsorted(sd.t.values, m.t_pub.values).clip(1, len(sd) - 1)
    j = np.where(np.abs(sd.t.values[i] - m.t_pub.values) < np.abs(sd.t.values[i - 1] - m.t_pub.values), i, i - 1)
    gap = np.abs(sd.t.values[j] - m.t_pub.values)
    m["band"] = LB.band_of(np.where(gap <= max_gap_s, sd.signal.values[j], np.nan))
    m = m[~in_scan & m.band.notna() & m.latency_ms.notna()]
    return m[["t_pub", "qos", "band", "latency_ms"]]


def bench_runs(base):
    """base_final per run, as metrics.analyse_run: (qos, run, t_pub_s, latency_ms, in_scan)."""
    out = []
    for rdir in sorted(glob.glob(os.path.join(base, "qos*_rep*"))):
        qos = int(re.match(r"qos(\d+)_rep", os.path.basename(rdir)).group(1))
        got = pd.read_csv(f"{rdir}/rx.csv").sort_values("t_rx_ns").drop_duplicates(["topic", "seq"], keep="first")
        tp = got.t_pub_ns.values / 1e9
        in_scan = np.zeros(len(got), bool)
        for a_, b_ in read_scans(rdir):
            in_scan |= (tp >= a_ - SCAN_MARGIN_S) & (tp <= b_ + SCAN_MARGIN_S)
        out.append(pd.DataFrame({"qos": qos, "run": os.path.basename(rdir), "t_pub": tp,
                                 "latency_ms": got.latency_ms.values, "in_scan": in_scan}))
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------- bootstrap core
def n_blocks(t, B):
    return int(len(np.unique(np.floor(np.asarray(t) / B))))


STRETCH_GAP_S = 1.0


def stretches(t_sorted, gap=STRETCH_GAP_S):
    """Per message: index of the first message of its stretch and the stretch size (a stretch = run of
    messages with no gap > `gap` s; a cell's stretches are its contiguous pieces of time)."""
    n = len(t_sorted)
    new = np.r_[True, np.diff(t_sorted) > gap]
    sid = np.cumsum(new) - 1
    first = np.flatnonzero(new)
    size = np.diff(np.r_[first, n])
    return first[sid], size[sid]


def mbb_indices(t_sorted, B, R, rng, chunk):
    """Yield (r, n) index arrays into t_sorted: moving-block resamples of exactly n messages.

    Circular within each stretch (Politis & Romano's circular block bootstrap): the block starting at
    message i holds the stretch's messages in [t_i, t_i + B), wrapping past the stretch end to its start
    (a stretch shorter than B is cycled, so its messages are drawn as often as any other). Every message
    then has the same chance of being drawn (checked: inclusion frequency uniform). Without the wrap,
    messages near a stretch end are in fewer blocks; late messages cluster at band transitions, i.e. at
    stretch ends, and the plain version underestimated some cells' share > 20 ms by up to 4x (bootstrap
    mean / observed 0.25 in F1 QoS 0, -65 to -75)."""
    n = len(t_sorted)
    a, m = stretches(t_sorted)
    rel = np.arange(n) - a
    # unrolled time: the stretch repeated once, shifted by its span + one median spacing
    dt = np.diff(t_sorted)
    step = np.median(dt[dt <= STRETCH_GAP_S]) if (dt <= STRETCH_GAP_S).any() else 0.05
    period = t_sorted[a + m - 1] - t_sorted[a] + step
    L = np.empty(n, int)
    for s in np.unique(a):
        k = np.arange(s, s + m[s])
        reps = int(np.ceil(B / period[s])) + 1                     # enough copies to hold any block
        tt = np.concatenate([t_sorted[k] + j * period[s] for j in range(reps)])
        L[k] = np.searchsorted(tt, t_sorted[k] + B, side="left") - np.arange(m[s])
    K = int(np.ceil(1.5 * n / L.mean())) + 10
    p = np.arange(n)
    done = 0
    while done < R:
        r = min(chunk, R - done)
        S = rng.integers(0, n, size=(r, K))
        Ls = L[S]
        while (Ls.sum(1) < n).any():                        # rare: draw more blocks for every row
            extra = rng.integers(0, n, size=(r, K))
            S = np.hstack([S, extra]); Ls = L[S]
        cum = np.cumsum(Ls, 1)
        off = int(cum[:, -1].max()) + 1
        rows = np.arange(r)[:, None] * off
        flatcum = (cum + rows).ravel()
        q = (p[None, :] + rows).ravel()
        b = np.searchsorted(flatcum, q, side="right")      # block that holds output position q
        s0 = S.ravel()[b]
        pos = q - (flatcum[b] - Ls.ravel()[b])                     # position inside the block
        idx = a[s0] + (rel[s0] + pos) % m[s0]                      # wrap inside the stretch
        yield idx.reshape(r, n)
        done += r


def boot_cell(t, lat, B, R, rng, qs=(50, 95), chunk=None):
    """Resampled exceedance counts (R,) and quantiles (len(qs), R) for one cell."""
    o = np.argsort(t, kind="stable")
    ts, ls = np.asarray(t)[o], np.asarray(lat)[o]
    chunk = chunk or max(50, int(4e6 // max(len(ts), 1)))
    exc, Q = [], []
    for idx in mbb_indices(ts, B, R, rng, chunk):
        V = ls[idx]
        exc.append((V > THR).sum(1))
        Q.append(np.percentile(V, qs, axis=1))
    return np.concatenate(exc), np.concatenate(Q, axis=1)


def ci(a):
    lo, hi = np.percentile(a, [2.5, 97.5])
    return lo, hi


def verdict(lo, hi, small=False):
    v = "excludes 0 (> 0)" if lo > 0 else "excludes 0 (< 0)" if hi < 0 else "includes 0: inconclusive"
    return v + ("; small cell" if small else "")


# ---------------------------------------------------------------- 1 + 2: flights
def flights_part(blocks, R):
    msgs = {lab: flight_msgs(os.path.join(D, path)) for lab, _, path in FLIGHTS}
    ref = pd.read_csv(os.path.join(D, "link_bands", "link_bands_per_flight.csv"))
    cells, boots = [], {}
    for B in blocks:
        for lab, name, _ in FLIGHTS:
            m = msgs[lab]
            for q in (0, 1, 2):
                for band in BANDS:
                    g = m[(m.qos == q) & (m.band == band)]
                    if not len(g):
                        continue
                    n, lat, t = len(g), g.latency_ms.values, g.t_pub.values
                    exc, Q = boot_cell(t, lat, B, R, rng_for("flight", name, q, band, B))
                    nb = n_blocks(t, B)
                    boots[(B, lab, q, band)] = (exc, n)
                    s_lo, s_hi = ci(100 * exc / n)
                    p50_lo, p50_hi = ci(Q[0]); p95_lo, p95_hi = ci(Q[1])
                    k = int((lat > THR).sum())
                    cells.append({"block_s": B, "flight": lab, "run": name, "qos": q, "band": BAND_NAME[band],
                                  "n": n, "blocks": nb, "n_gt20": k,
                                  "gt20_pct": 100 * k / n, "gt20_lo": s_lo, "gt20_hi": s_hi,
                                  "p50": np.percentile(lat, 50), "p50_lo": p50_lo, "p50_hi": p50_hi,
                                  "p95": np.percentile(lat, 95), "p95_lo": p95_lo, "p95_hi": p95_hi,
                                  "too_small": bool(n < MIN_N or nb < MIN_BLOCKS)})
    C = pd.DataFrame(cells)
    # check against the published per-flight table
    chk = C[C.block_s == blocks[0]].merge(
        ref.assign(band=ref.band.map(BAND_NAME)), left_on=["run", "qos", "band"], right_on=["flight", "qos", "band"],
        suffixes=("", "_ref"))
    if len(chk) != len(ref) or (chk.n != chk.n_ref).any() or \
            max((chk.p50 - chk.p50_ref).abs().max(), (chk.p95 - chk.p95_ref).abs().max(),
                (chk.gt20_pct - chk.gt20_pct_ref).abs().max()) > 1e-9:
        raise SystemExit("flight cells do not reproduce link_bands_per_flight.csv")
    print(f"check: {len(chk)} flight cells reproduce link_bands_per_flight.csv (n, p50, p95, % > 20 ms)")

    small = {(r.block_s, r.flight, r.qos, BANDS[list(BAND_NAME.values()).index(r.band)]): r.too_small
             for r in C.itertuples()}
    comps = []

    def add(B, kind, flight, what, cells_a, cells_b, ref_band=""):
        """cells_*: list of (flight, qos, band); pooled when several (stratified sum)."""
        def pooled(cs):
            e = sum(boots[(B,) + c][0] for c in cs); n = sum(boots[(B,) + c][1] for c in cs)
            pt = sum(int(((msgs[c[0]].qos == c[1]) & (msgs[c[0]].band == c[2]) & (msgs[c[0]].latency_ms > THR)).sum())
                     for c in cs)
            return 100 * e / n, 100 * pt / n, n
        a, pa, na = pooled(cells_a); b, pb, nb_ = pooled(cells_b)
        lo, hi = ci(a - b)
        sm = any(small[(B,) + c] for c in cells_a + cells_b)
        comps.append({"block_s": B, "kind": kind, "flight": flight, "comparison": what, "ref_band": ref_band,
                      "n_a": na, "n_b": nb_, "a_pct": pa, "b_pct": pb, "diff_pp": pa - pb, "lo": lo, "hi": hi,
                      "excludes_0": bool(lo > 0 or hi < 0), "verdict": verdict(lo, hi, sm)})

    weak = "-75 to -65"
    # b) reference = strongest band whose QoS 2 cell is not too small at the primary block length
    # (chosen once, kept for every block length so the sensitivity check compares the same cells)
    pb = PRIMARY_B if PRIMARY_B in blocks else blocks[0]
    refb = {}
    for lab, _, _ in FLIGHTS:
        cand = [bd for bd in BANDS if bd != weak and (pb, lab, 2, bd) in boots and not small[(pb, lab, 2, bd)]]
        if cand and (pb, lab, 2, weak) in boots:
            refb[lab] = cand[0]
    for B in blocks:
        for lab, _, _ in FLIGHTS:
            if all((B, lab, q, weak) in boots for q in (0, 1, 2)):
                add(B, "a", lab, "QoS2 - QoS1, -65 to -75", [(lab, 2, weak)], [(lab, 1, weak)])
                add(B, "a", lab, "QoS2 - QoS0, -65 to -75", [(lab, 2, weak)], [(lab, 0, weak)])
            if lab in refb:
                add(B, "b", lab, "QoS2: -65 to -75 minus strongest band", [(lab, 2, weak)], [(lab, 2, refb[lab])],
                    BAND_NAME[refb[lab]])
        fl = [lab for lab, _, _ in FLIGHTS]
        add(B, "c", "pooled", "QoS2 - QoS1, -65 to -75", [(f, 2, weak) for f in fl], [(f, 1, weak) for f in fl])
        add(B, "c", "pooled", "QoS2 - QoS0, -65 to -75", [(f, 2, weak) for f in fl], [(f, 0, weak) for f in fl])
        add(B, "c", "pooled", "QoS2: -65 to -75 minus strongest band", [(f, 2, weak) for f in refb],
            [(f, 2, refb[f]) for f in refb], "+".join(f"{f}:{BAND_NAME[refb[f]]}" for f in refb))
    return C, pd.DataFrame(comps)


# ---------------------------------------------------------------- 3: bench base_final
def bench_part(blocks, R):
    BR = bench_runs(os.path.join(D, "base_final"))
    ref = pd.read_csv(os.path.join(D, "base_final", "metrics_pooled.csv"))
    ref = ref[ref.group == "qos"] if "group" in ref else ref
    rows = []
    for q in (0, 1, 2):
        for scans in ("with", "without"):
            g = BR[(BR.qos == q) & ((~BR.in_scan) if scans == "without" else True)]
            lat = g.latency_ms.values
            pt = {"p95": np.percentile(lat, 95), "p99": np.percentile(lat, 99), "gt20_pct": 100 * np.mean(lat > THR)}
            r0 = ref[ref.qos == q].iloc[0]
            pre = "lat_" if scans == "with" else "noscan_lat_"
            if max(abs(pt["p95"] - r0[pre + "p95_ms"]), abs(pt["p99"] - r0[pre + "p99_ms"]),
                   abs(pt["gt20_pct"] - r0[pre + "over20_pct"])) > 1e-9:
                raise SystemExit(f"base_final QoS {q} {scans} scans does not reproduce metrics_pooled.csv")
            runs = [x.latency_ms.values for _, x in g.groupby("run")]
            base = {"qos": q, "scans": scans, "n": len(lat), "runs": len(runs), "n_gt20": int((lat > THR).sum()), **pt}
            # run-level bootstrap
            rng = rng_for("bench_run", q, scans)
            pick = rng.integers(0, len(runs), size=(R, len(runs)))
            st = np.empty((R, 3))
            for i, pk in enumerate(pick):
                v = np.concatenate([runs[k] for k in pk])
                st[i] = (*np.percentile(v, [95, 99]), 100 * np.mean(v > THR))
            distinct = len({tuple(sorted(pk)) for pk in pick.tolist()})
            rows.append({**base, "method": "runs", "block_s": np.nan, "blocks": len(runs),
                         **{f"{k}_lo": ci(st[:, j])[0] for j, k in enumerate(("p95", "p99", "gt20"))},
                         **{f"{k}_hi": ci(st[:, j])[1] for j, k in enumerate(("p95", "p99", "gt20"))},
                         "note": f"{distinct} distinct run multisets"})
            # 2 s (and 1, 5 s) moving blocks, stratified by run
            for B in blocks:
                parts = []
                for run, x in g.groupby("run"):
                    o = np.argsort(x.t_pub.values, kind="stable")
                    ts, ls = x.t_pub.values[o], x.latency_ms.values[o]
                    parts.append((ts, ls, mbb_indices(ts, B, R, rng_for("bench_blk", q, scans, run, B), 500)))
                st = []
                while True:
                    try:
                        V = np.hstack([ls[next(it)] for _, ls, it in parts])
                    except StopIteration:
                        break
                    st.append(np.column_stack([*np.percentile(V, [95, 99], axis=1), 100 * (V > THR).mean(1)]))
                st = np.vstack(st)
                nb = sum(n_blocks(x.t_pub.values, B) for _, x in g.groupby("run"))
                rows.append({**base, "method": "blocks", "block_s": B, "blocks": nb,
                             **{f"{k}_lo": ci(st[:, j])[0] for j, k in enumerate(("p95", "p99", "gt20"))},
                             **{f"{k}_hi": ci(st[:, j])[1] for j, k in enumerate(("p95", "p99", "gt20"))},
                             "note": "stratified by run"})
    print("check: base_final p95, p99, % > 20 ms (with and without scans) reproduce metrics_pooled.csv")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- output
def fmt_ci(v, lo, hi, d=2):
    return f"{v:.{d}f} [{lo:.{d}f}, {hi:.{d}f}]"


def md(df):
    return "\n".join(["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
                     + ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resamples", type=int, default=10000)
    ap.add_argument("--blocks", default="1,2,5")
    ap.add_argument("--out", default=os.path.join(D, "ci"))
    a = ap.parse_args()
    blocks = [float(x) for x in a.blocks.split(",")]
    os.makedirs(a.out, exist_ok=True)
    C, K = flights_part(blocks, a.resamples)
    Bn = bench_part(blocks, a.resamples)
    C.to_csv(os.path.join(a.out, "flight_bands_ci.csv"), index=False)
    K.to_csv(os.path.join(a.out, "comparisons_ci.csv"), index=False)
    Bn.to_csv(os.path.join(a.out, "bench_base_final_ci.csv"), index=False)

    P = C[C.block_s == PRIMARY_B]
    t1 = pd.DataFrame({"flight": P.flight, "QoS": P.qos, "band dBm": P.band, "n": P.n, "blocks": P.blocks,
                       "> 20 ms % [95% CI]": [fmt_ci(r.gt20_pct, r.gt20_lo, r.gt20_hi) for r in P.itertuples()],
                       "p50 ms [95% CI]": [fmt_ci(r.p50, r.p50_lo, r.p50_hi) for r in P.itertuples()],
                       "p95 ms [95% CI]": [fmt_ci(r.p95, r.p95_lo, r.p95_hi) for r in P.itertuples()],
                       "flag": np.where(P.too_small, "too small", "")})
    # sensitivity of the cell CIs: width of the % > 20 and p95 interval per block length
    W = C.pivot_table(index=["flight", "qos", "band"], columns="block_s",
                      values=["gt20_lo", "gt20_hi", "p95_lo", "p95_hi"]).reset_index()
    sens_cells = pd.DataFrame({"flight": W.flight, "QoS": W.qos, "band": W.band})
    for B in blocks:
        sens_cells[f"> 20 % CI, {B:g} s"] = [f"[{lo:.2f}, {hi:.2f}]" for lo, hi in zip(W[("gt20_lo", B)], W[("gt20_hi", B)])]
    for B in blocks:
        sens_cells[f"p95 CI, {B:g} s"] = [f"[{lo:.2f}, {hi:.2f}]" for lo, hi in zip(W[("p95_lo", B)], W[("p95_hi", B)])]
    KP = K[K.block_s == PRIMARY_B]
    t2 = pd.DataFrame({"part": KP.kind, "flight": KP.flight, "comparison": KP.comparison, "ref band": KP.ref_band,
                       "n a / b": [f"{r.n_a} / {r.n_b}" for r in KP.itertuples()],
                       "a %": KP.a_pct.round(2), "b %": KP.b_pct.round(2),
                       "diff pp [95% CI]": [fmt_ci(r.diff_pp, r.lo, r.hi) for r in KP.itertuples()],
                       "verdict": KP.verdict})
    S = K.pivot_table(index=["kind", "flight", "comparison"], columns="block_s", values=["lo", "hi", "excludes_0"],
                      aggfunc="first").reset_index()
    sens = pd.DataFrame({"part": S.kind, "flight": S.flight, "comparison": S.comparison})
    for B in blocks:
        sens[f"{B:g} s"] = [f"[{lo:.2f}, {hi:.2f}] {'excl. 0' if ex else 'incl. 0'}"
                            for lo, hi, ex in zip(S[("lo", B)], S[("hi", B)], S[("excludes_0", B)])]
    sens["same verdict"] = [len({S[("excludes_0", B)].iloc[i] for B in blocks}) == 1 for i in range(len(S))]
    bt = Bn.copy()
    bt["method"] = [("runs (5)" if r.method == "runs" else f"blocks {r.block_s:g} s") for r in bt.itertuples()]
    t3 = pd.DataFrame({"QoS": bt.qos, "scans": bt.scans, "method": bt.method, "n": bt.n, "units": bt.blocks,
                       "p95 ms [95% CI]": [fmt_ci(r.p95, r.p95_lo, r.p95_hi) for r in bt.itertuples()],
                       "p99 ms [95% CI]": [fmt_ci(r.p99, r.p99_lo, r.p99_hi) for r in bt.itertuples()],
                       "> 20 ms % [95% CI]": [fmt_ci(r.gt20_pct, r.gt20_lo, r.gt20_hi, 3) for r in bt.itertuples()],
                       "note": bt.note})
    hdr = (f"Moving-block bootstrap, {a.resamples} resamples, seed {SEED}, percentile 95% intervals; blocks of "
           f"{', '.join(f'{b:g}' for b in blocks)} s (primary {PRIMARY_B:g} s). First-arrival latency per unique "
           f"message, same selection as link_bands.py / metrics.py (point estimates checked against the published "
           f"tables). Bands: > -55, (-65, -55], (-75, -65], <= -75 dBm. Too small: n < {MIN_N} or blocks < "
           f"{MIN_BLOCKS}. A share of 0 events gives a degenerate [0, 0] interval: the bootstrap cannot bound it "
           f"from above.")
    for fn, title, tab in [("flight_bands_ci.md", f"Flights by RSSI band ({PRIMARY_B:g} s blocks)", t1),
                           ("comparisons_ci.md", f"Comparisons, % > 20 ms differences in percentage points ({PRIMARY_B:g} s blocks)", t2),
                           ("bench_base_final_ci.md", "Bench base_final (Table 3)", t3)]:
        open(os.path.join(a.out, fn), "w").write(f"# {title}\n\n{hdr}\n\n{md(tab)}\n")
    open(os.path.join(a.out, "sensitivity_blocks.md"), "w").write(
        f"# Block-length sensitivity\n\n{hdr}\n\n## Comparisons\n\n{md(sens)}\n\n## Cells\n\n{md(sens_cells)}\n")
    sens.to_csv(os.path.join(a.out, "sensitivity_comparisons.csv"), index=False)
    sens_cells.to_csv(os.path.join(a.out, "sensitivity_cells.csv"), index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 20); pd.set_option("display.max_rows", 200)
    for title, tab in [("FLIGHTS", t1), ("COMPARISONS", t2), ("BLOCK SENSITIVITY", sens), ("BENCH base_final", t3)]:
        print(f"\n== {title}\n{tab.to_string(index=False)}")
    print(f"\nwritten to {a.out}")


if __name__ == "__main__":
    main()
