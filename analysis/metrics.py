#!/usr/bin/env python3
"""Per-run and pooled metrics for a campaign or field session.

For every run folder (any sub-folder of data/<name>/ with meta.json, rx.csv and pi_log.csv):
  - delivery: PDR / PLR from pi_log.csv (sent) vs rx.csv (received), unique (topic, seq);
  - latency (first arrival of each message): mean, jitter (= std), p50/p95/p99/max, % > 20 ms;
  - throughput: received messages/s and payload kbit/s over the publish window; update rate
    per topic (received messages/s);
  - mean MQTT payload bytes per topic, and the aggregate data rate
    R = sum_i f_i * S_i * 8 (f_i = received update rate, S_i = mean payload bytes of topic i;
    our reading of the abstract's Eq. 8: payload only, no MQTT/TCP/IP headers);
  - Age of Information per topic at the laptop, from t_sample_ns (Pi clock) and t_rx_ns
    (laptop clock; chrony keeps them within ~1 ms): time-average AoI over [first reception,
    last reception] (sawtooth integral, only fresher samples reset the age) and peak AoI
    (age just before each reset): mean, p95 and max;
  - RSSI from pi_side/station_dump.log (falls back to wifi_before/after.txt);
  - scans from pi_side/iw_event.log: count, mean duration, share of the run time.
Pooled per QoS, and per (distance_m, QoS) when meta.json has distance_m:
  latency percentiles from all messages, PDR from summed counts, AoI as the duration-weighted
  mean of run averages (peak: max over runs).
Writes data/<name>/metrics_runs.csv, metrics_pooled.csv and metrics.md.

Usage: python analysis/metrics.py <name or folder> [...]
"""
import glob, json, os, re, sys
import numpy as np, pandas as pd

HOME = os.path.expanduser("~/uav-mqtt/data")
THRESH_MS = 20.0


def run_dirs(base):
    out = []
    for m in sorted(glob.glob(f"{base}/**/meta.json", recursive=True)):
        d = os.path.dirname(m)
        if os.path.exists(f"{d}/rx.csv") and os.path.exists(f"{d}/pi_log.csv"):
            out.append(d)
    return out


def aoi(s_ns, r_ns):
    """Time-average and peak AoI (ms) from sample and reception times of one topic."""
    o = np.argsort(r_ns, kind="stable")
    s, r = np.asarray(s_ns, float)[o] / 1e6, np.asarray(r_ns, float)[o] / 1e6
    keep, newest = [], -np.inf                    # only fresher samples reset the age
    for i in range(len(s)):
        if s[i] > newest:
            keep.append(i)
            newest = s[i]
    s, r = s[keep], r[keep]
    if len(s) < 2:
        return np.nan, np.array([])
    dt = np.diff(r)
    a0 = r[:-1] - s[:-1]                          # age right after each reset
    a1 = r[1:] - s[:-1]                           # age just before the next reset (peak)
    area = np.sum(dt * (a0 + a1) / 2)
    return area / (r[-1] - r[0]), a1


def rssi(rdir, side, t0, t1):
    """Signal from the station dump inside [t0, t1] (dump blocks start with 'T <unix time>')."""
    f = f"{side}/station_dump.log"
    v = []
    if os.path.exists(f):
        t = None
        for line in open(f):
            if line.startswith("T "):
                t = float(line.split()[1])
            else:
                m = re.match(r"^\s*signal:\s*(-?\d+)", line)
                if m and t is not None and t0 <= t <= t1:
                    v.append(int(m.group(1)))
    src = "station_dump"
    if not v:
        src = "wifi_before/after"
        for n in ("wifi_before.txt", "wifi_after.txt"):
            if os.path.exists(f"{rdir}/{n}"):
                v += [int(x) for x in re.findall(r"signal:\s*(-?\d+)", open(f"{rdir}/{n}").read())]
    if not v:
        return {"rssi_src": None}
    v = np.array(v)
    return {"rssi_src": src, "rssi_n": len(v), "rssi_mean_dbm": v.mean(), "rssi_p5_dbm": np.percentile(v, 5),
            "rssi_min_dbm": v.min(), "rssi_max_dbm": v.max()}


SCAN_MARGIN_S = 1.0     # "without scans": drop messages published in [scan start - 1 s, scan end + 1 s]


def scan_windows(side):
    """(start, end) of every completed scan in pi_side/iw_event.log; None if not logged."""
    f = f"{side}/iw_event.log"
    if not os.path.exists(f):
        return None
    ev = [(float(m.group(1)), m.group(2)) for m in
          re.finditer(r"^(\d+\.\d+): \S+ \(phy #\d+\): scan (started|finished|aborted)", open(f).read(), re.M)]
    out, start = [], None
    for t, k in ev:
        if k == "started":
            start = t
        elif start is not None:
            out.append((start, t))
            start = None
    return out


def scans(wins, t0, t1):
    if wins is None:
        return {"scans": None}
    dur = [b - a for a, b in wins if t0 <= a <= t1]
    return {"scans": len(dur), "scan_mean_s": np.mean(dur) if dur else 0.0,
            "scan_time_pct": 100 * sum(dur) / (t1 - t0)}


def clock_check(rdir, side, meta, t0, t1, stall_lastrx_s=None, max_offset_ms=None):
    """Flag a run whose clock may have stalled: chrony_after.txt (LastRx if the sources table is
    there, System time offset) and, if side logging ran, chrony.log samples inside [t0, t1].
    Stall = LastRx > 60 s (campaign_lib.STALL_LASTRX_S): 15-30 s is normal over Wi-Fi."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "code"))
    from campaign_lib import parse_lastrx, STALL_LASTRX_S, MAX_OFFSET_MS
    max_lastrx_s = STALL_LASTRX_S if stall_lastrx_s is None else stall_lastrx_s
    max_offset_ms = MAX_OFFSET_MS if max_offset_ms is None else max_offset_ms
    r, why = {}, []
    f = os.path.join(rdir, meta.get("chrony_after", "chrony_after.txt"))
    txt = open(f).read() if os.path.exists(f) else ""
    m = re.search(r"System time\s*:\s*([\d.]+) seconds (slow|fast)", txt)
    r["clk_after_offset_ms"] = float(m.group(1)) * 1e3 * (1 if m.group(2) == "fast" else -1) if m else np.nan
    m = re.search(r"^\S+\s+192\.168\.1\.4\s+\d+\s+\d+\s+\d+\s+(\S+)", txt, re.M)
    r["clk_after_lastrx_s"] = parse_lastrx(m.group(1)) if m else np.nan
    # A sample at time t with LastRx L means no update in [t - L, t]: it concerns this run if that
    # interval overlaps [t0, t1]. Offsets count only from samples taken inside the run.
    lr, off, n = [], [], 0
    g = f"{side}/chrony.log"
    if os.path.exists(g):
        for line in open(g):
            mt = re.match(r"(\d+\.\d+) \S+\s+192\.168\.1\.4\s+\d+\s+\d+\s+\d+\s+(\S+)", line)
            mo = re.search(r"System time\s*:\s*([\d.]+) seconds (slow|fast)", line)
            if not mt:
                continue
            t, L = float(mt.group(1)), parse_lastrx(mt.group(2))
            if t0 <= t <= t1:
                n += 1
                if mo:
                    off.append(float(mo.group(1)) * 1e3)
            if t - min(L, 1e9) <= t1 and t >= t0:
                lr.append(L)
    r["clk_log_n"] = n
    r["clk_log_max_lastrx_s"] = max(lr) if lr else np.nan
    r["clk_log_max_abs_offset_ms"] = max(off) if off else np.nan
    if r["clk_after_lastrx_s"] > max_lastrx_s:
        why.append(f"chrony_after LastRx {r['clk_after_lastrx_s']:.0f} s (stalled)")
    if abs(r["clk_after_offset_ms"]) > max_offset_ms:
        why.append(f"chrony_after |offset| {abs(r['clk_after_offset_ms']):.2f} ms")
    if lr and max(lr) > max_lastrx_s:
        why.append(f"during run LastRx up to {max(lr):.0f} s (stalled)")
    if off and max(off) > max_offset_ms:
        why.append(f"during run |offset| up to {max(off):.2f} ms")
    r["clock_flag"] = "; ".join(why)
    return r


def latency_stats(v, prefix="lat_"):
    v = np.asarray(v, float)
    if not len(v):
        return {}
    return {f"{prefix}mean_ms": v.mean(), f"{prefix}jitter_ms": v.std(ddof=1) if len(v) > 1 else np.nan,
            f"{prefix}p50_ms": np.percentile(v, 50), f"{prefix}p95_ms": np.percentile(v, 95),
            f"{prefix}p99_ms": np.percentile(v, 99), f"{prefix}max_ms": v.max(),
            f"{prefix}over20_pct": 100 * np.mean(v > THRESH_MS)}


def analyse_run(rdir, base):
    meta = json.load(open(f"{rdir}/meta.json"))
    pl = pd.read_csv(f"{rdir}/pi_log.csv", usecols=["topic", "seq", "t_sample_ns", "t_pub_ns", "bytes"])
    pl = pl.drop_duplicates(["topic", "seq"])
    rx = pd.read_csv(f"{rdir}/rx.csv").sort_values("t_rx_ns").drop_duplicates(["topic", "seq"], keep="first")
    df = pl.merge(rx[["topic", "seq", "t_rx_ns", "latency_ms", "bytes"]], on=["topic", "seq"],
                  how="left", suffixes=("_sent", "_rx"))
    df["sensor"] = df.topic.str.split("/").str[-1]
    got = df[df.t_rx_ns.notna()]
    t0, t1 = df.t_pub_ns.min() / 1e9, df.t_pub_ns.max() / 1e9
    T = t1 - t0
    side = os.path.normpath(os.path.join(rdir, meta.get("side_dir", "pi_side")))
    r = {"name": os.path.basename(base), "run": os.path.relpath(rdir, base), "qos": meta.get("qos"),
         "distance_m": meta.get("distance_m"), "point": meta.get("point"),
         "label": meta.get("label", meta.get("run_id")),
         "duration_s": T, "nodelay": meta.get("nodelay"), "sidelog": meta.get("sidelog"),
         "stadump_s": meta.get("stadump_s"), "ping_hz": meta.get("ping_hz"), "pcap": meta.get("pcap"),
         "sent": len(df), "received": len(got), "extra_in_rx": int(len(rx) - len(got)),
         "pdr_pct": 100 * len(got) / len(df), "plr_pct": 100 * (1 - len(got) / len(df)),
         "msgs_per_s": len(got) / T, "payload_kbps": got.bytes_rx.sum() * 8 / T / 1e3}
    r.update(latency_stats(got.latency_ms.values))
    wins = scan_windows(side)
    in_scan = np.zeros(len(got), bool)
    for a_, b_ in wins or []:
        tp = got.t_pub_ns.values / 1e9
        in_scan |= (tp >= a_ - SCAN_MARGIN_S) & (tp <= b_ + SCAN_MARGIN_S)
    got = got.assign(in_scan=in_scan)
    r["msgs_in_scan"] = int(in_scan.sum())
    r.update(latency_stats(got[~got.in_scan].latency_ms.values, prefix="noscan_lat_"))
    nominal = {"mpu6050": meta.get("imu_hz", 20.0), "bmp280": meta.get("bmp_hz", 2.0), "ina219": meta.get("ina_hz", 2.0)}
    agg = agg_nom = 0.0
    for s, g in df.groupby("sensor"):
        gr = g[g.t_rx_ns.notna()]
        f_i, S_i = len(gr) / T, gr.bytes_rx.mean() if len(gr) else np.nan
        agg += f_i * (S_i if len(gr) else 0) * 8
        # nominal: publisher rate x mean payload of what was sent (Table 2 of the abstract)
        agg_nom += nominal.get(s, np.nan) * g.bytes_sent.mean() * 8
        r[f"{s}_nominal_hz"] = nominal.get(s, np.nan)
        avg, peaks = aoi(gr.t_sample_ns.values, gr.t_rx_ns.values) if len(gr) else (np.nan, np.array([]))
        r.update({f"{s}_pdr_pct": 100 * len(gr) / len(g), f"{s}_rate_hz": f_i, f"{s}_bytes": S_i,
                  f"{s}_lat_p50_ms": gr.latency_ms.median(), f"{s}_lat_p99_ms": gr.latency_ms.quantile(.99),
                  f"{s}_aoi_avg_ms": avg,
                  f"{s}_paoi_mean_ms": peaks.mean() if len(peaks) else np.nan,
                  f"{s}_paoi_p95_ms": np.percentile(peaks, 95) if len(peaks) else np.nan,
                  f"{s}_paoi_max_ms": peaks.max() if len(peaks) else np.nan})
    r["agg_rate_measured_kbps"] = agg / 1e3
    r["agg_rate_nominal_kbps"] = agg_nom / 1e3
    r.update(rssi(rdir, side, t0, t1))
    r.update(scans(wins, t0, t1))
    r.update(clock_check(rdir, side, meta, t0, t1))
    return r, got[["sensor", "latency_ms", "in_scan"]].assign(
        qos=meta.get("qos"), distance_m=meta.get("distance_m"), nodelay=meta.get("nodelay"),
        pcap=meta.get("pcap") or 0, ping_hz=meta.get("ping_hz") or 0)


def pooled(R, lat, keys):
    rows = []
    sensors = sorted({c.split("_")[0] for c in R.columns if c.endswith("_aoi_avg_ms")})
    for k, g in R.groupby(keys, dropna=False):
        k = k if isinstance(k, tuple) else (k,)
        m = np.ones(len(lat), bool)
        for col, val in zip(keys, k):
            m &= (lat[col].isna() if pd.isna(val) else lat[col] == val).values
        row = dict(zip(keys, k))
        row.update(runs=len(g), sent=int(g.sent.sum()), received=int(g.received.sum()),
                   pdr_pct=100 * g.received.sum() / g.sent.sum(),
                   plr_pct=100 * (1 - g.received.sum() / g.sent.sum()),
                   msgs_per_s=g.received.sum() / g.duration_s.sum(),
                   payload_kbps=(g.payload_kbps * g.duration_s).sum() / g.duration_s.sum(),
                   agg_rate_measured_kbps=(g.agg_rate_measured_kbps * g.duration_s).sum() / g.duration_s.sum(),
                   agg_rate_nominal_kbps=(g.agg_rate_nominal_kbps * g.duration_s).sum() / g.duration_s.sum(),
                   clock_flagged_runs=int((g.clock_flag != "").sum()))
        row.update(latency_stats(lat[m].latency_ms.values))
        row["msgs_in_scan"] = int(lat[m].in_scan.sum())
        row.update(latency_stats(lat[m & ~lat.in_scan.values].latency_ms.values, prefix="noscan_lat_"))
        w = g.duration_s
        for s in sensors:
            row[f"{s}_rate_hz"] = (g[f"{s}_rate_hz"] * w).sum() / w.sum()
            row[f"{s}_bytes"] = g[f"{s}_bytes"].mean()
            row[f"{s}_aoi_avg_ms"] = (g[f"{s}_aoi_avg_ms"] * w).sum() / w.sum()
            row[f"{s}_paoi_mean_ms"] = (g[f"{s}_paoi_mean_ms"] * w).sum() / w.sum()
            row[f"{s}_paoi_max_ms"] = g[f"{s}_paoi_max_ms"].max()
        if "rssi_mean_dbm" in g:
            row["rssi_mean_dbm"] = g.rssi_mean_dbm.mean()
            row["rssi_min_dbm"] = g.rssi_min_dbm.min()
        if "scans" in g and g.scans.notna().any():
            row["scans"] = g.scans.sum()
            row["scan_time_pct"] = (g.scan_time_pct * w).sum() / w.sum()
        rows.append(row)
    return pd.DataFrame(rows)


def md_table(df, cols, fmt):
    cols = [c for c in cols if c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            cells.append("" if pd.isna(v) else (fmt.get(c, "{:.2f}").format(v) if isinstance(v, (int, float, np.number)) else str(v)))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


for name in sys.argv[1:]:
    base = os.path.abspath(name) if os.path.isdir(name) else f"{HOME}/{name}"
    name = os.path.basename(base.rstrip("/"))
    dirs = run_dirs(base)
    if not dirs:
        print(f"{name}: no run folders with meta.json, rx.csv and pi_log.csv")
        continue
    rows, lats = [], []
    for d in dirs:
        r, l = analyse_run(d, base)
        rows.append(r)
        lats.append(l)
    R, LAT = pd.DataFrame(rows), pd.concat(lats, ignore_index=True)
    P = pooled(R, LAT, ["qos"])
    P.insert(0, "group", "qos")
    if R.distance_m.notna().any():
        PD = pooled(R, LAT, ["distance_m", "qos"])
        PD.insert(0, "group", "distance_qos")
        P = pd.concat([P, PD], ignore_index=True)
    R["pcap"], R["ping_hz"] = R.pcap.fillna(0), R.ping_hz.fillna(0)
    factors = [f for f in ("nodelay", "pcap", "ping_hz") if R[f].nunique(dropna=False) > 1]
    if factors:                                  # interleaved A/B: pool per condition as well
        PC = pooled(R, LAT, ["qos"] + factors)
        PC.insert(0, "group", "condition")
        P = pd.concat([P, PC], ignore_index=True)
    R.to_csv(f"{base}/metrics_runs.csv", index=False)
    P.to_csv(f"{base}/metrics_pooled.csv", index=False)

    sensors = sorted({c.split("_")[0] for c in R.columns if c.endswith("_aoi_avg_ms")})
    fmt = {"sent": "{:.0f}", "received": "{:.0f}", "runs": "{:.0f}", "qos": "{:.0f}", "scans": "{:.0f}",
           "pdr_pct": "{:.3f}", "plr_pct": "{:.3f}", "lat_over20_pct": "{:.3f}", "noscan_lat_over20_pct": "{:.3f}", "msgs_in_scan": "{:.0f}", "distance_m": "{:.0f}", "nodelay": "{:.0f}", "pcap": "{:.0f}", "ping_hz": "{:g}",
           "rssi_mean_dbm": "{:.1f}", "rssi_min_dbm": "{:.0f}", "duration_s": "{:.0f}"}
    cols_noscan = ["group", "distance_m", "qos", "scans", "msgs_in_scan", "noscan_lat_mean_ms", "noscan_lat_jitter_ms",
                   "noscan_lat_p50_ms", "noscan_lat_p95_ms", "noscan_lat_p99_ms", "noscan_lat_max_ms",
                   "noscan_lat_over20_pct"]
    cols_lat = ["group", "distance_m", "qos", "runs", "sent", "received", "pdr_pct", "plr_pct", "lat_mean_ms",
                "lat_jitter_ms", "lat_p50_ms", "lat_p95_ms", "lat_p99_ms", "lat_max_ms", "lat_over20_pct"]
    cols_rate = ["group", "distance_m", "qos", "msgs_per_s", "payload_kbps", "agg_rate_nominal_kbps",
                 "agg_rate_measured_kbps"] + \
                [f"{s}_{x}" for s in sensors for x in ("rate_hz", "bytes")] + ["rssi_mean_dbm", "rssi_min_dbm", "scans", "scan_time_pct"]
    cols_aoi = ["group", "distance_m", "qos"] + [f"{s}_{x}" for s in sensors for x in ("aoi_avg_ms", "paoi_mean_ms", "paoi_max_ms")]
    run_cols = ["run", "qos", "distance_m", "duration_s", "sent", "received", "pdr_pct", "lat_mean_ms", "lat_jitter_ms",
                "lat_p50_ms", "lat_p95_ms", "lat_p99_ms", "lat_max_ms", "lat_over20_pct", "agg_rate_measured_kbps",
                "mpu6050_aoi_avg_ms", "mpu6050_paoi_max_ms", "rssi_mean_dbm", "scans", "scan_time_pct",
                "clk_after_offset_ms", "clk_log_max_lastrx_s"]
    for c in (cols_lat, cols_noscan):
        for f_ in [f for f in ("nodelay", "pcap", "ping_hz") if f in P.columns]:
            c.insert(c.index("qos") + 1, f_)
    if R.distance_m.isna().all():
        for c in (cols_lat, cols_rate, cols_aoi, run_cols, cols_noscan):
            c.remove("distance_m")
    else:
        run_cols.insert(1, "point")
    md = [f"# Metrics: `{name}`", "",
          f"{len(R)} runs. Latency = laptop receive - Pi publish (first arrival). Jitter = std of latency. "
          f"PDR from unique (topic, seq) in pi_log.csv vs rx.csv. Aggregate rate (Eq. 8) R = sum f_k S_k x 8, "
          f"S_k = mean payload bytes (payload only): nominal = publisher rates (as in the abstract's Table 2), "
          f"measured = received update rates. AoI from t_sample_ns at the laptop; "
          f"pooled AoI = duration-weighted mean of run averages, peak = max over runs.", "",
          "## Clock check", "",
          (("Runs flagged (chrony LastRx > 60 s (stalled) or |offset| > 1 ms after or during the run; the clock may "
            "have stalled, so latency and AoI may be biased):\n\n" +
            "\n".join(f"- `{r.run}`: {r.clock_flag}" for r in R.itertuples() if r.clock_flag))
           if (R.clock_flag != "").any() else "No run flagged (chrony LastRx <= 60 s and |offset| <= 1 ms "
           "after the run, and during it where side logging recorded chrony)."), "",
          "## Delivery and latency (pooled, ms)", "", md_table(P, cols_lat, fmt), "",
          f"## Latency without scan windows (ms; messages published within {SCAN_MARGIN_S:.0f} s of an `iw event` scan removed)", "",
          md_table(P, cols_noscan, fmt), "",
          "## Rates, payload, link", "", md_table(P, cols_rate, fmt), "",
          "## Age of Information (ms)", "", md_table(P, cols_aoi, fmt), "",
          "## Per run", "", md_table(R, run_cols, fmt), ""]
    open(f"{base}/metrics.md", "w").write("\n".join(md))
    print("\n".join(md))
    print(f"\nwrote {base}/metrics_runs.csv, metrics_pooled.csv, metrics.md")
