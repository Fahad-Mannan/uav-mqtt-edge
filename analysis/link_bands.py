#!/usr/bin/env python3
"""Pool flights by link quality: QoS x RSSI band (and hover/transit), from flight_position.py outputs.

Inputs per flight folder: position/msgs_pos.csv (from flight_position.py: every sent message with
t_pub, qos, latency_ms, position bin) and pi_side/station_dump.log (iw station dump, ~1 s).
Each message gets the RSSI of the nearest station-dump sample (within --max-gap-s, else dropped
from the band table and counted). Bands (dBm): > -55, (-65, -55], (-75, -65], <= -75.
Only hover_* and transit bins are used (ground and no_position left out); `kind` = hover / transit / all.
Messages published within 1 s of an `iw event` scan are left out (counted in the header).

Wi-Fi counters per band: brcmfmac's station dump has no retry counter, only `tx failed` (cumulative)
and `tx packets`; each interval between consecutive dump samples is assigned to the band of its
later sample, and the counter increments are summed per band (only intervals inside the flight's
segment windows). Also the median/mean tx bitrate per band. Counters pooled and per flight.

--legs f3,f4: for those out-and-back flights also outbound / far hold / return x distance band
(0-50, 50-100, 100-150, > 150 m from flight_position.py's origin) x QoS, with RSSI and the median tx
bitrate of the nearest station-dump sample (link_legs.csv).

Usage: python analysis/link_bands.py data/field_2026-11-22/f1b data/field_2026-11-23/f2b [--legs f3,f4] [--out DIR]
Writes DIR/link_bands.csv, link_bands_per_flight.csv, link_counters.csv, link_counters_per_flight.csv,
link_legs.csv (with --legs) and link_bands.md (default DIR: data/link_bands/).
"""
import argparse, os, re
import numpy as np
import pandas as pd

BANDS = [(-55, np.inf, "> -55"), (-65, -55, "-65 to -55"), (-75, -65, "-75 to -65"), (-np.inf, -75, "<= -75")]


def band_of(dbm):
    out = np.full(len(dbm), None, dtype=object)
    for lo, hi, name in BANDS:
        out[(dbm > lo) & (dbm <= hi)] = name
    return out


def station(path):
    rows, cur = [], None
    for line in open(path):
        if line.startswith("T "):
            if cur:
                rows.append(cur)
            cur = {"t": float(line.split()[1])}
        elif cur is not None:
            m = re.match(r"\s*(signal|tx failed|tx packets|tx bitrate):\s*(-?[\d.]+)", line)
            if m:
                cur[m.group(1).replace(" ", "_")] = float(m.group(2))
    if cur:
        rows.append(cur)
    return pd.DataFrame(rows).dropna(subset=["signal"]).sort_values("t").reset_index(drop=True)


def scans(path):
    out, st = [], None
    if os.path.exists(path):
        for line in open(path):
            m = re.match(r"([\d.]+): .*scan (started|finished|aborted)", line)
            if m:
                if m.group(2) == "started":
                    st = float(m.group(1))
                elif st is not None:
                    out.append((st, float(m.group(1))))
                    st = None
    return out


DIST_BANDS = [(0, 50, "0-50"), (50, 100, "50-100"), (100, 150, "100-150"), (150, np.inf, ">150")]


def dist_band(d):
    out = np.full(len(d), None, dtype=object)
    for lo, hi, name in DIST_BANDS:
        out[(d >= lo) & (d < hi)] = name
    return out


def leg_of(m):
    """hover/transit messages of an out-and-back flight -> 'out' / 'hold' / 'back'.
    hold = any hover bin and the transit between the first and the last hover message (the far-point
    hold; f4 drifted between two detected hover distances); out = transit before it (includes the
    check hover over the takeoff spot, < 5 m, so in the 0-50 band); back = transit after it."""
    hv = m.bin.str.startswith("hover")
    if not hv.any():
        return np.where(m.t_pub.values < m.t_pub.values[np.nanargmax(m.dist_m.values)], "out", "back")
    t0, t1 = m.t_pub[hv].min(), m.t_pub[hv].max()
    return np.where(m.t_pub < t0, "out", np.where(m.t_pub > t1, "back", "hold"))


def stats(L):
    return {"n": len(L), "p50": L.quantile(.5), "p95": L.quantile(.95), "p99": L.quantile(.99), "max": L.max(),
            "gt20_pct": 100 * (L > 20).mean()} if len(L) else {"n": 0}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("flights", nargs="+")
    p.add_argument("--max-gap-s", type=float, default=1.5)
    p.add_argument("--out", default=None)
    p.add_argument("--legs", default="",
                   help="comma-separated flight names (folder names) that are out-and-back: also tabulate "
                        "outbound / far hold / return x distance band (DIST_BANDS) x QoS from msgs_pos.csv dist_m "
                        "(distance from flight_position.py's origin; use --origin there for the router)")
    a = p.parse_args()
    legs = [x for x in a.legs.split(",") if x]
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "link_bands")
    os.makedirs(out, exist_ok=True)
    msgs, ctr, notes = [], [], []
    for f in a.flights:
        name = os.path.basename(f.rstrip("/"))
        m = pd.read_csv(os.path.join(f, "position", "msgs_pos.csv"))
        if "bin" not in m:
            raise SystemExit(f"{f}: msgs_pos.csv has no 'bin' column; re-run flight_position.py")
        sd = station(os.path.join(f, "pi_side", "station_dump.log"))
        sc = scans(os.path.join(f, "pi_side", "iw_event.log"))
        m = m[m.bin.str.startswith("hover") | (m.bin == "transit")].copy()
        m["kind"] = np.where(m.bin.str.startswith("hover"), "hover", "transit")
        in_scan = np.zeros(len(m), bool)
        for s0, s1 in sc:
            in_scan |= (m.t_pub.values >= s0 - 1) & (m.t_pub.values <= s1 + 1)
        i = np.searchsorted(sd.t.values, m.t_pub.values).clip(1, len(sd) - 1)
        j = np.where(np.abs(sd.t.values[i] - m.t_pub.values) < np.abs(sd.t.values[i - 1] - m.t_pub.values), i, i - 1)
        gap = np.abs(sd.t.values[j] - m.t_pub.values)
        m["rssi"] = np.where(gap <= a.max_gap_s, sd.signal.values[j], np.nan)
        m["band"] = band_of(m.rssi.values)
        notes.append(f"{name}: {len(m)} hover/transit messages, {int(in_scan.sum())} within 1 s of a scan "
                     f"({len(sc)} scans) left out, {int(m.rssi.isna().sum())} without a station-dump sample "
                     f"within {a.max_gap_s:g} s, {int((~m.rcvd).sum())} not received")
        m["flight"] = name
        m["tx_bitrate"] = np.where(gap <= a.max_gap_s, sd.tx_bitrate.values[j], np.nan)
        m["leg"] = leg_of(m) if name in legs else None
        msgs.append(m[~in_scan])
        # counters: intervals inside the flight's segment windows, band of the later sample
        seg = pd.read_csv(os.path.join(f, "segments.csv"))
        inside = np.zeros(len(sd), bool)
        for _, s in seg.iterrows():
            inside |= (sd.t.values >= s.actual_start_unix) & (sd.t.values <= s.end_unix)
        d = sd.copy()
        d["d_failed"] = d.tx_failed.diff()
        d["d_packets"] = d.tx_packets.diff()
        d["band"] = band_of(d.signal.values)
        d["flight"] = name
        ctr.append(d[inside & d.d_failed.notna() & (d.d_failed >= 0)])
    M = pd.concat(msgs, ignore_index=True)
    C = pd.concat(ctr, ignore_index=True)
    rows = []
    order = [b[2] for b in BANDS]
    for q in sorted(M.qos.unique()):
        for band in order:
            for kind in ("hover", "transit", "all"):
                g = M[(M.qos == q) & (M.band == band) & ((M.kind == kind) if kind != "all" else True)]
                if not len(g):
                    continue
                r = {"qos": int(q), "band": band, "kind": kind, "sent": len(g), "rcvd": int(g.rcvd.sum()),
                     "pdr_pct": 100 * g.rcvd.mean(), "flights": "+".join(sorted(g.flight.unique())),
                     "rssi_mean": g.rssi.mean()}
                r.update(stats(g.latency_ms.dropna()))
                rows.append(r)
    T = pd.DataFrame(rows)
    # per flight (all kinds): the flights come from sessions with different body latency (refs differ by
    # several ms), and the bands are not filled equally by each flight, so the pooled rows mix both effects
    rows = []
    for q in sorted(M.qos.unique()):
        for band in order:
            for fl in sorted(M.flight.unique()):
                g = M[(M.qos == q) & (M.band == band) & (M.flight == fl)]
                if len(g):
                    r = {"qos": int(q), "band": band, "flight": fl, "sent": len(g), "rssi_mean": g.rssi.mean()}
                    r.update(stats(g.latency_ms.dropna()))
                    rows.append(r)
    P = pd.DataFrame(rows)
    W = []
    for band in order:
        g = C[C.band == band]
        if len(g):
            W.append({"band": band, "dump_samples": len(g), "tx_packets": int(g.d_packets.sum()),
                      "tx_failed": int(g.d_failed.sum()),
                      "failed_per_1000_packets": 1000 * g.d_failed.sum() / g.d_packets.sum() if g.d_packets.sum() else np.nan,
                      "samples_with_failures": int((g.d_failed > 0).sum()),
                      "tx_bitrate_median": g.tx_bitrate.median(), "tx_bitrate_mean": g.tx_bitrate.mean(),
                      "tx_bitrate_min": g.tx_bitrate.min()})
    W = pd.DataFrame(W)
    # the same per flight (the bitrate as median too)
    WF = []
    for fl in sorted(C.flight.unique()):
        for band in order:
            g = C[(C.band == band) & (C.flight == fl)]
            if len(g):
                WF.append({"flight": fl, "band": band, "dump_samples": len(g), "tx_packets": int(g.d_packets.sum()),
                           "tx_failed": int(g.d_failed.sum()),
                           "failed_per_1000_packets": 1000 * g.d_failed.sum() / g.d_packets.sum() if g.d_packets.sum() else np.nan,
                           "tx_bitrate_median": g.tx_bitrate.median(), "tx_bitrate_mean": g.tx_bitrate.mean()})
    WF = pd.DataFrame(WF)
    # out-and-back flights: leg x distance band x QoS
    D = []
    for fl in legs:
        g0 = M[M.flight == fl].copy()
        if not len(g0):
            continue
        g0["dband"] = dist_band(g0.dist_m.values)
        for q in sorted(g0.qos.unique()):
            for leg in ("out", "hold", "back"):
                for db in [b[2] for b in DIST_BANDS]:
                    g = g0[(g0.qos == q) & (g0.leg == leg) & (g0.dband == db)]
                    if len(g):
                        L = g.latency_ms.dropna()
                        D.append({"flight": fl, "qos": int(q), "leg": leg, "dist_band_m": db, "n": len(g),
                                  "rcvd": int(g.rcvd.sum()), "p50": L.quantile(.5), "p95": L.quantile(.95),
                                  "max": L.max(), "gt20_pct": 100 * (L > 20).mean(), "rssi_mean": g.rssi.mean(),
                                  "tx_bitrate_median": g.tx_bitrate.median()})
    D = pd.DataFrame(D)
    if len(D):
        D.to_csv(os.path.join(out, "link_legs.csv"), index=False)
    T.to_csv(os.path.join(out, "link_bands.csv"), index=False)
    P.to_csv(os.path.join(out, "link_bands_per_flight.csv"), index=False)
    W.to_csv(os.path.join(out, "link_counters.csv"), index=False)
    WF.to_csv(os.path.join(out, "link_counters_per_flight.csv"), index=False)

    def md(df):
        f = lambda v: f"{v:.2f}" if isinstance(v, (float, np.floating)) else str(v)
        return "\n".join(["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
                         + ["| " + " | ".join(f(v) for v in r) + " |" for r in df.itertuples(index=False)])
    cols = ["qos", "band", "kind", "sent", "rcvd", "pdr_pct", "n", "p50", "p95", "p99", "max", "gt20_pct", "rssi_mean", "flights"]
    lines = ["# Latency by QoS x RSSI band (" + ", ".join(os.path.basename(f.rstrip('/')) for f in a.flights) + ")", "",
             "RSSI = nearest station-dump sample (Pi side, `signal`). Bands in dBm: " +
             ", ".join(b[2] for b in BANDS) + ". Hover and transit bins from flight_position.py; ground and refs "
             "left out; scan windows (+-1 s) left out.", ""] + [f"- {n}" for n in notes] + ["", md(T[cols]), "",
             "Per flight (hover + transit): sessions differ in body latency, so compare bands within a flight:", "",
             md(P[["qos", "band", "flight", "n", "p50", "p95", "p99", "max", "gt20_pct", "rssi_mean"]]), "",
             "Wi-Fi counters per band (station dump; brcmfmac reports no retries, only `tx failed`; intervals "
             "inside the segment windows, band of the later sample), pooled:", "", md(W), "", "Per flight:", "", md(WF)]
    if len(D):
        lines += ["", "Out-and-back flights: leg x distance band from the origin (outbound / far hold / return):", "",
                  md(D)]
    open(os.path.join(out, "link_bands.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
