#!/usr/bin/env python3
"""Weak-signal QoS 2 bench test: latency by QoS per position, and where QoS 2's extra delay goes.

Input: one or more run folders from code/run_weak_link.py (run_field.py flight mode with --pcap 1
--sidelog 1), e.g. data/weak_link_p2m/r1. Each has segments.csv, one folder per segment (rx.csv,
pi_log.csv, meta.json), capture.pcapng (enp0s31f6 + lo, CONNECT filtered out) and pi_side/
(station_dump.log, iw_event.log, system.log, chrony.log).

Per position x QoS (pooled over segments) and per segment:
  - n sent, PDR, latency p50/p95/p99, share > 20 ms (first arrival per unique message, laptop
    receive - Pi publish, as everywhere else), scans;
  - median RSSI, tx and rx bitrate, tx failed / tx packets (station dump inside the segment window;
    brcmfmac reports no retry counter), under-voltage (vcgencmd throttled) in the window.
Latency split, from the capture at the laptop NIC (enp0s31f6) and on lo (broker <-> logger):
  QoS 2: lat = (a) PUBLISH Pi -> NIC   A1 - t_pub        one-way, needs the Pi/laptop clock sync
             + (r) broker turnaround   A2 - A1           PUBLISH in -> PUBREC out
             + (b) radio round trip    A3 - A2           PUBREC out -> PUBREL in, clock-free
                                                          (Wi-Fi down + Pi processing + Wi-Fi up)
             + (c) broker -> logger    t_rx - A3         Mosquitto forwards a QoS 2 message on PUBREL
  QoS 1: lat = (a) A1 - t_pub + (c) t_rx - A1             (forwarded on PUBLISH)
  QoS 0: the same as QoS 1.
  The sum (a)+(r)+(b)+(c) = lat exactly (one laptop clock for A*, t_rx; checked).
  Round trips that exist for both QoS 1 and 2, clock-free:
    rt_tcp: broker's PUBACK (QoS 1) / PUBREC (QoS 2) out -> the Pi's first TCP ACK covering it.
            The same radio path for both QoS; it may wait for the Pi's delayed ACK unless the Pi
            sends data (a PUBLISH, or the PUBREL) first, so compare its distribution, not one value.
    (b) is QoS 2 only: QoS 1 has no MQTT-level reply to PUBACK.
  rt_tcp's tail (gt30_pct) is the Pi's delayed ACK: for QoS 1 the Pi often has nothing to send right
  away, for QoS 2 the PUBREL goes out at once and carries the ACK. Compare rt_tcp by its median.
  The one-way (a) is flagged when the Pi's chrony (pi_side/chrony.log) reports |System time| > 1 ms
  or LastRx > 60 s during the run.

Usage: python analysis/weak_link_qos2.py data/weak_link_<pos>/r1 [data/weak_link_<pos2>/r1 ...] [--out DIR]
Writes <run>/weak_link/{segments.csv, messages.csv, summary.md} per run and
DIR/{weak_link_summary.csv, weak_link_split.csv, weak_link_summary.md} over all runs
(default DIR: data/weak_link_summary/).
"""
import argparse, glob, json, os, re, sys
from bisect import bisect_left
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from pcap_qos2_handshake import load_connections, sdiff  # noqa: E402

THR = 20.0
SCAN_MARGIN_S = 1.0          # as metrics.py (not imported: it runs its campaign loop at import)


# ---------------------------------------------------------------- Pi side logs
def station(path):
    rows, cur = [], None
    if not os.path.exists(path):
        return pd.DataFrame(columns=["t", "signal"])
    for line in open(path, errors="replace"):
        if line.startswith("T "):
            if cur:
                rows.append(cur)
            cur = {"t": float(line.split()[1])}
        elif cur is not None:
            m = re.match(r"\s*(signal|tx failed|tx packets|rx packets|tx bitrate|rx bitrate|tx retries):\s*(-?[\d.]+)", line)
            if m:
                cur[m.group(1).replace(" ", "_")] = float(m.group(2))
    if cur:
        rows.append(cur)
    return pd.DataFrame(rows).dropna(subset=["signal"]).sort_values("t").reset_index(drop=True)


def scans(path):
    out, st = [], None
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            m = re.match(r"([\d.]+): .*scan (started|finished|aborted)", line)
            if m:
                if m.group(2) == "started":
                    st = float(m.group(1))
                elif st is not None:
                    out.append((st, float(m.group(1)))); st = None
    return out


def throttled(path):
    rows = []
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            m = re.match(r"([\d.]+) throttled=(0x[0-9a-fA-F]+)", line)
            if m:
                rows.append((float(m.group(1)), int(m.group(2), 16)))
    return pd.DataFrame(rows, columns=["t", "thr"])


def chrony(path):
    """Per reading: t, LastRx (s), |System time| (ms)."""
    rows = []
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            m = re.match(r"([\d.]+) \^\*\s+\S+\s+\d+\s+\d+\s+\d+\s+(\d+)(\w?)", line)
            s = re.search(r"System time\s*:\s*([\d.]+) seconds (slow|fast)", line)
            if m:
                lr = int(m.group(2)) * {"": 1, "m": 60, "h": 3600, "d": 86400}.get(m.group(3), 1)
                rows.append((float(m.group(1)), lr, 1e3 * float(s.group(1)) if s else np.nan))
            elif re.match(r"[\d.]+ ", line) and s:   # no selected source in this reading
                rows.append((float(line.split()[0]), np.inf, 1e3 * float(s.group(1))))
    return pd.DataFrame(rows, columns=["t", "lastrx_s", "systime_ms"])


# ---------------------------------------------------------------- capture
def match_publisher(c):
    """Per PUBLISH (c2s) on one publisher connection: A1, broker reply (PUBACK / PUBREC) A2 and its
    end seq, PUBREL A3 (QoS 2), PUBCOMP A4, the Pi's TCP ACK covering the reply. Key: (topic, t_pub_ns)."""
    recs, open_ = {}, {}
    for e in c["events"]:
        typ, pid = e["type"], e.get("pid")
        if typ == "PUBLISH" and e["dir"] == "c2s":
            if e["qos"] and e["dup"] and pid in open_:
                open_[pid]["n_dup"] += 1
                continue
            r = {"topic": e["topic"], "seq": e["seq"], "t_pub_ns": e["t_pub_ns"], "qos": e["qos"], "A1": e["t"], "n_dup": 0}
            recs[(e["topic"], e["t_pub_ns"])] = r
            if e["qos"]:
                open_[pid] = r
        elif pid in open_:
            r = open_[pid]
            if typ in ("PUBACK", "PUBREC") and e["dir"] == "s2c" and "A2" not in r:
                r["A2"], r["end2"] = e["t"], e["end"]
                if typ == "PUBACK":
                    del open_[pid]
            elif typ == "PUBREL" and e["dir"] == "c2s" and "A3" not in r:
                r["A3"] = e["t"]
            elif typ == "PUBCOMP" and e["dir"] == "s2c":
                r["A4"] = e["t"]; del open_[pid]
    acks = c["c2s_acks"]
    ack_t = [x[0] for x in acks]
    for r in recs.values():
        if "A2" in r:
            for x in acks[bisect_left(ack_t, r["A2"]):]:
                if x[0] - r["A2"] > 10 ** 9:
                    break
                if sdiff(x[1], r["end2"]) >= 0:
                    r["ACK2"] = x[0]; break
    return recs


def capture_legs(pcap):
    """(publisher records by (topic, t_pub_ns) with the connection id, logger-leg B1 by (topic, t_pub_ns),
    per-connection health)."""
    conns = load_connections(pcap)
    A, B, health = {}, {}, []
    for k, c in conns.items():
        n_c2s = sum(e["dir"] == "c2s" and e["type"] == "PUBLISH" for e in c["events"])
        n_s2c = sum(e["dir"] == "s2c" and e["type"] == "PUBLISH" for e in c["events"])
        h = {"iface": c["iface"], "client": c["client"], "publishes_in": n_c2s, "publishes_out": n_s2c,
             **{f"{d}_{x}": getattr(c[d], x) for d in ("c2s", "s2c") for x in ("gaps", "retrans", "start_skip", "bad")}}
        if n_c2s and c["iface"] != "lo":
            for key, r in match_publisher(c).items():
                A[key] = dict(r, conn=c["client"])
            h["role"] = "publisher"
        elif n_s2c and c["iface"] == "lo":
            for e in c["events"]:
                if e["type"] == "PUBLISH" and e["dir"] == "s2c":
                    B.setdefault((e["topic"], e["t_pub_ns"]), e["t"])
            h["role"] = "logger"
        else:
            h["role"] = "other"
        health.append(h)
    return A, B, health


# ---------------------------------------------------------------- per run
def pct(v, q):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    return float(np.percentile(v, q)) if len(v) else np.nan


def lat_stats(v, prefix=""):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if not len(v):
        return {f"{prefix}n": 0}
    return {f"{prefix}n": len(v), f"{prefix}p50": pct(v, 50), f"{prefix}p95": pct(v, 95), f"{prefix}p99": pct(v, 99),
            f"{prefix}max": float(v.max()), f"{prefix}gt20_pct": 100 * float(np.mean(v > THR))}


def analyse_run(run):
    seg = pd.read_csv(os.path.join(run, "segments.csv"))
    side = os.path.join(run, "pi_side")
    sd, sc, th, ch = station(os.path.join(side, "station_dump.log")), scans(os.path.join(side, "iw_event.log")), \
        throttled(os.path.join(side, "system.log")), chrony(os.path.join(side, "chrony.log"))
    pcap = os.path.join(run, "capture.pcapng")
    A, B, health = capture_legs(pcap) if os.path.exists(pcap) else ({}, {}, [])
    msgs, segrows = [], []
    for s in seg.itertuples():
        d = os.path.join(run, s.label)
        if not os.path.exists(os.path.join(d, "pi_log.csv")):
            continue
        pl = pd.read_csv(os.path.join(d, "pi_log.csv"), usecols=["topic", "seq", "t_pub_ns"]).drop_duplicates(["topic", "seq"])
        rx = pd.read_csv(os.path.join(d, "rx.csv")).sort_values("t_rx_ns").drop_duplicates(["topic", "seq"], keep="first")
        m = pl.merge(rx[["topic", "seq", "t_rx_ns", "latency_ms"]], on=["topic", "seq"], how="left")
        m["segment"], m["qos"], m["point"] = s.label, int(s.qos), s.point
        tp = m.t_pub_ns.values / 1e9
        m["in_scan"] = False
        for a_, b_ in sc:
            m.loc[(tp >= a_ - SCAN_MARGIN_S) & (tp <= b_ + SCAN_MARGIN_S), "in_scan"] = True
        for col in ("A1", "A2", "A3", "A4", "ACK2", "B1"):
            m[col] = pd.array([None] * len(m), dtype="Int64")
        conn = []
        for i, (topic, t) in enumerate(zip(m.topic, m.t_pub_ns)):
            r = A.get((topic, int(t)))
            if r:
                for col in ("A1", "A2", "A3", "A4", "ACK2"):
                    if col in r:
                        m.iat[i, m.columns.get_loc(col)] = r[col]
            b = B.get((topic, int(t)))
            if b is not None:
                m.iat[i, m.columns.get_loc("B1")] = b
            conn.append(r["conn"] if r else None)
        m["conn"] = conn
        g = lambda x, y: ((m[x] - m[y]) / 1e6).astype(float)
        m["a_ms"] = g("A1", "t_pub_ns")
        if s.qos == 2:
            m["r_ms"], m["b_ms"], m["c_ms"] = g("A2", "A1"), g("A3", "A2"), g("t_rx_ns", "A3")
            m["fwd_ms"] = g("B1", "A3")
        else:
            m["r_ms"], m["b_ms"] = np.nan, np.nan
            m["c_ms"], m["fwd_ms"] = g("t_rx_ns", "A1"), g("B1", "A1")
        m["rt_tcp_ms"] = g("ACK2", "A2") if s.qos else np.nan
        m["deliv_logger_ms"] = g("t_rx_ns", "B1")
        # NaN when a part is missing (e.g. a PUBREL lost from the reassembled stream after a TCP retransmission)
        parts = m[["a_ms", "r_ms", "b_ms", "c_ms"]].sum(axis=1, skipna=False) if s.qos == 2 else m.a_ms + m.c_ms
        m["sum_resid_ms"] = parts - m.latency_ms
        msgs.append(m)
        # segment context
        w = (sd.t >= s.actual_start_unix) & (sd.t <= s.end_unix) if len(sd) else []
        sw = sd[w] if len(sd) else sd
        tw = th[(th.t >= s.actual_start_unix) & (th.t <= s.end_unix)] if len(th) else th
        r = {"point": s.point, "segment": s.label, "qos": int(s.qos), "start_unix": s.actual_start_unix,
             "sent": len(m), "received": int(m.t_rx_ns.notna().sum()), "pdr_pct": 100 * m.t_rx_ns.notna().mean(),
             "scans": sum(1 for a_, b_ in sc if b_ >= s.actual_start_unix and a_ <= s.end_unix),
             "in_capture": int(m.A1.notna().sum()),
             "rssi_med": sw.signal.median() if len(sw) else np.nan, "rssi_min": sw.signal.min() if len(sw) else np.nan,
             "tx_bitrate_med": sw.tx_bitrate.median() if "tx_bitrate" in sw and len(sw) else np.nan,
             "rx_bitrate_med": sw.rx_bitrate.median() if "rx_bitrate" in sw and len(sw) else np.nan,
             "tx_failed": float(sw.tx_failed.max() - sw.tx_failed.min()) if "tx_failed" in sw and len(sw) > 1 else np.nan,
             "tx_packets": float(sw.tx_packets.max() - sw.tx_packets.min()) if "tx_packets" in sw and len(sw) > 1 else np.nan,
             "undervolt": bool(((tw.thr & 0x1) != 0).any()) if len(tw) else None,
             "conns": len({c for c in conn if c})}
        r.update(lat_stats(m.latency_ms))
        for k in ("a_ms", "r_ms", "b_ms", "c_ms", "rt_tcp_ms"):
            r[f"{k[:-3]}_p50"], r[f"{k[:-3]}_p95"] = pct(m[k], 50), pct(m[k], 95)
        segrows.append(r)
    M, S = pd.concat(msgs, ignore_index=True), pd.DataFrame(segrows)
    t0, t1 = seg.actual_start_unix.min(), seg.end_unix.max()
    cw = ch[(ch.t >= t0 - 15) & (ch.t <= t1 + 15)] if len(ch) else ch
    clock = {"readings": len(cw), "max_lastrx_s": float(cw.lastrx_s.max()) if len(cw) else None,
             "max_systime_ms": float(cw.systime_ms.max()) if len(cw) else None}
    clock["flag"] = bool(len(cw) == 0 or clock["max_lastrx_s"] > 60 or clock["max_systime_ms"] > 1.0)
    return M, S, health, clock


def pooled(M, S):
    rows = []
    for (pt, q), g in M.groupby(["point", "qos"]):
        s = S[(S.point == pt) & (S.qos == q)]
        r = {"point": pt, "qos": int(q), "segments": len(s), "sent": len(g), "received": int(g.t_rx_ns.notna().sum()),
             "pdr_pct": 100 * g.t_rx_ns.notna().mean()}
        r.update(lat_stats(g.latency_ms))
        r.update(lat_stats(g.latency_ms[~g.in_scan], "noscan_"))
        r.update(rssi_med=s.rssi_med.median(), tx_bitrate_med=s.tx_bitrate_med.median(),
                 rx_bitrate_med=s.rx_bitrate_med.median(), tx_failed=s.tx_failed.sum(), tx_packets=s.tx_packets.sum(),
                 scans=int(s.scans.sum()), undervolt_segments=int((s.undervolt == True).sum()),  # noqa: E712
                 in_capture_pct=100 * g.A1.notna().mean())
        rows.append(r)
    return pd.DataFrame(rows)


def split_table(M):
    """Medians and p95 of each latency component, per position x QoS (messages present in the capture)."""
    rows = []
    for (pt, q), g in M.groupby(["point", "qos"]):
        g = g[g.A1.notna() & g.t_rx_ns.notna()]
        for comp, label in [("latency_ms", "end-to-end"), ("a_ms", "(a) Pi publish -> NIC (one-way, clock)"),
                            ("r_ms", "(r) broker PUBLISH in -> PUBREC out"),
                            ("b_ms", "(b) PUBREC out -> PUBREL in (radio RTT, clock-free)"),
                            ("c_ms", "(c) broker -> logger (from PUBREL; QoS 0/1 from PUBLISH)"),
                            ("fwd_ms", "  (c1) ... -> broker PUBLISH to logger on lo"),
                            ("deliv_logger_ms", "  (c2) broker PUBLISH on lo -> logger on_message"),
                            ("rt_tcp_ms", "PUBACK/PUBREC out -> Pi TCP ACK (radio RTT, clock-free)")]:
            v = g[comp].astype(float).dropna()
            if len(v):
                rows.append({"point": pt, "qos": int(q), "component": label, "n": len(v), "p50": pct(v, 50),
                             "p95": pct(v, 95), "p99": pct(v, 99), "mean": float(v.mean()),
                             # share over 30 ms: for rt_tcp, the Pi's delayed ACK (no data to send at once);
                             # QoS 1 tails are dominated by it, so compare rt_tcp between QoS by the median
                             "gt30_pct": 100 * float((v > 30).mean())})
    return pd.DataFrame(rows)


def md(df, digits=2):
    f = lambda v: f"{v:.{digits}f}" if isinstance(v, (float, np.floating)) else str(v)
    return "\n".join(["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
                     + ["| " + " | ".join(f(v) for v in r) + " |" for r in df.itertuples(index=False)])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "weak_link_summary"))
    a = ap.parse_args()
    allM, allS, notes = [], [], []
    for run in a.runs:
        M, S, health, clock = analyse_run(run)
        M["run"] = S["run"] = "/".join(os.path.normpath(run).split(os.sep)[-2:])
        od = os.path.join(run, "weak_link"); os.makedirs(od, exist_ok=True)
        S.to_csv(os.path.join(od, "segments.csv"), index=False)
        keep = [c for c in M.columns if c not in ("conn",)]
        M[keep].to_csv(os.path.join(od, "messages.csv"), index=False)
        resid = M.sum_resid_ms.abs().max()
        incomplete = int((M.t_rx_ns.notna() & M.A1.notna() & M.sum_resid_ms.isna()).sum())
        pubs = [h for h in health if h["role"] == "publisher"]
        n = (f"{run}: {len(S)} segments, {len(pubs)} publisher connections in the capture "
             f"(TCP retransmissions Pi->broker {sum(h['c2s_retrans'] for h in pubs)}, broker->Pi "
             f"{sum(h['s2c_retrans'] for h in pubs)}; reassembly gaps {sum(h['c2s_gaps'] + h['s2c_gaps'] for h in pubs)}), "
             f"messages in capture {100 * M.A1.notna().mean():.1f}%, max |sum of parts - latency| {resid:.6f} ms "
             f"({incomplete} received messages with a handshake step missing from the capture); "
             f"Pi clock: {clock['readings']} chrony readings, max LastRx {clock['max_lastrx_s']} s, max |System time| "
             f"{clock['max_systime_ms']} ms -> {'FLAGGED: one-way (a) unreliable' if clock['flag'] else 'ok'}")
        notes.append(n)
        P, T = pooled(M, S), split_table(M)
        open(os.path.join(od, "summary.md"), "w").write(
            f"# Weak-link QoS test: `{run}`\n\n- {n}\n\n## By QoS\n\n{md(P)}\n\n## Latency split (ms)\n\n{md(T)}\n\n"
            f"## Per segment\n\n{md(S.drop(columns=['run']))}\n")
        allM.append(M); allS.append(S)
    M, S = pd.concat(allM, ignore_index=True), pd.concat(allS, ignore_index=True)
    P, T = pooled(M, S), split_table(M)
    os.makedirs(a.out, exist_ok=True)
    P.to_csv(os.path.join(a.out, "weak_link_summary.csv"), index=False)
    T.to_csv(os.path.join(a.out, "weak_link_split.csv"), index=False)
    cols = ["point", "qos", "segments", "sent", "pdr_pct", "n", "p50", "p95", "p99", "max", "gt20_pct",
            "rssi_med", "tx_bitrate_med", "rx_bitrate_med", "tx_failed", "tx_packets", "scans", "undervolt_segments",
            "in_capture_pct"]
    text = (f"# Weak-link QoS test: {len(a.runs)} run(s)\n\n" + "\n".join(f"- {n}" for n in notes) +
            f"\n\nLatency = laptop receive - Pi publish, first arrival per unique message (ms). RSSI / bitrate = "
            f"median of the per-segment medians (station dump, 1 s).\n\n## By position and QoS\n\n{md(P[cols])}\n\n"
            f"## Latency split by position and QoS (ms)\n\n{md(T)}\n\n## Per segment\n\n"
            f"{md(S[['run', 'segment', 'qos', 'sent', 'pdr_pct', 'p50', 'p95', 'gt20_pct', 'b_p50', 'b_p95', 'rt_tcp_p50', 'rt_tcp_p95', 'rssi_med', 'tx_bitrate_med', 'tx_failed', 'scans', 'undervolt']])}\n")
    open(os.path.join(a.out, "weak_link_summary.md"), "w").write(text)
    print(text)


if __name__ == "__main__":
    main()
