#!/usr/bin/env python3
"""Align MQTT spike episodes with Pi scan events, pings and the packet capture, for runs made
with run_campaign.py --sidelog 1 [--ping HZ] [--pcap 1].

Pre-specified H1 checks (set before L1):
  - episode = >= 10 messages over 20 ms with publish gaps < 1 s (as in spike_episodes.py);
    episode start/end = publish time of its first/last message over 20 ms;
  - match: an iw-event scan whose start is within +-1 s of the episode start AND whose end is
    within +-1 s of the episode end;
  - ping: in [episode start - 1 s, episode end + 1 s], Pi ping has replies over 20 ms and
    router ping has none;
  - capture: for delayed messages, the delay is before the laptop NIC (Pi publish -> PUBLISH at
    enp0s31f6), not after (NIC -> logger receive);
  - sched_lag in the episode not above its value in the 5 s before (+1 ms margin).
Background latency is reported outside +-5 s of every episode and every scan.

Usage: python analysis/align_sidelog.py <campaign> [<run> ...]
"""
import glob, json, os, re, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pcap_qos2_handshake import load_connections

THRESH_MS, MIN_N, GAP_S, TOL_S, BG_EXCL_S = 20.0, 10, 1.0, 1.0, 5.0
PI_IP = "192.168.1.3"
HOME = os.path.expanduser("~/uav-mqtt/data")

def pct(v):
    v = np.asarray(v, float)
    if not len(v):
        return "n=0"
    return (f"n={len(v)} p50 {np.percentile(v, 50):.2f} p95 {np.percentile(v, 95):.2f} "
            f"p99 {np.percentile(v, 99):.2f} max {v.max():.2f} >20ms {100 * np.mean(v > 20):.3f}%")

def load_ping(path):
    rows = []
    for line in open(path):
        m = re.match(r"\[(\d+\.\d+)\] \d+ bytes.*icmp_seq=(\d+).*time=([\d.]+) ms", line)
        if m:
            t_rx, rtt = float(m.group(1)), float(m.group(3))
            rows.append((int(m.group(2)), t_rx - rtt / 1e3, rtt))
    df = pd.DataFrame(rows, columns=["seq", "t_tx", "rtt"])
    sent = re.search(r"(\d+) packets transmitted, (\d+) received", open(path).read())
    return df, (int(sent.group(1)), int(sent.group(2))) if sent else (None, None)

def scans_of(path):
    ev = []
    for line in open(path):
        m = re.match(r"(\d+\.\d+): \S+ \(phy #\d+\): scan (started|finished|aborted)", line)
        if m:
            ev.append((float(m.group(1)), m.group(2)))
    out, start = [], None
    for t, k in ev:
        if k == "started":
            start = t
        elif start is not None:
            out.append((start, t, k))
            start = None
    return out

camp = sys.argv[1]
runs = sys.argv[2:] or sorted(os.path.basename(d) for d in glob.glob(f"{HOME}/{camp}/qos*_rep*"))
for run in runs:
    rdir = f"{HOME}/{camp}/{run}"
    meta = json.load(open(f"{rdir}/meta.json"))
    print(f"===== {camp}/{run}: QoS {meta['qos']}, {meta['duration_s']} s, nodelay {meta['nodelay']}, "
          f"stadump {meta.get('stadump_s')}, ping {meta.get('ping_hz')} Hz, pcap {meta.get('pcap')}")
    for tag in ("power_before", "power_after"):
        p = meta.get(tag)
        if p:
            lap, pi = p["laptop"], p["pi"]
            print(f"  {tag}: laptop {lap['driver']}/{','.join(lap['governor'])}/{','.join(lap['epp'])}/"
                  f"{lap['power_profile']}, AC {lap['power_supply_online'].get('AC')}, "
                  f"cur MHz {min(lap['cur_khz']) // 1000}-{max(lap['cur_khz']) // 1000} | "
                  f"Pi {','.join(pi.get('governor', []))}, ARM {pi.get('arm_hz', 0) / 1e6:.0f} MHz, "
                  f"throttled {pi.get('throttled')}")
    rx = pd.read_csv(f"{rdir}/rx.csv").drop_duplicates(["topic", "seq"])
    pl = pd.read_csv(f"{rdir}/pi_log.csv", usecols=["topic", "seq", "t_sample_ns", "t_pub_ns", "sched_lag_ms"])
    df = pl.merge(rx[["topic", "seq", "t_rx_ns", "latency_ms"]], on=["topic", "seq"], how="left")
    df = df.sort_values("t_pub_ns").reset_index(drop=True)
    df["sensor"] = df.topic.str.split("/").str[-1]
    df["tp"] = df.t_pub_ns / 1e9
    print(f"  messages: sent {len(pl)}, received {df.latency_ms.notna().sum()}")

    # episodes
    det = df[df.latency_ms > THRESH_MS]
    eps = []
    if len(det):
        gid = (det.tp.diff() > GAP_S).cumsum()
        eps = [(g.tp.min(), g.tp.max(), len(g), g.latency_ms.max()) for _, g in det.groupby(gid) if len(g) >= MIN_N]
    scans = scans_of(f"{rdir}/pi_side/iw_event.log")
    print(f"  episodes {len(eps)}, scans {len(scans)} "
          f"(aborted {sum(k == 'aborted' for *_, k in scans)}); scan durations "
          + ", ".join(f"{b - a:.3f}" for a, b, _ in scans) + " s; intervals "
          + ", ".join(f"{x:.3f}" for x in np.diff([a for a, _, _ in scans])) + " s")

    # pings
    pings = {}
    for tag in ("pi", "router"):
        f = f"{rdir}/ping_{tag}.txt"
        if os.path.exists(f):
            pings[tag] = load_ping(f)

    # capture: PUBLISH at enp0s31f6 from the Pi
    nic = None
    if os.path.exists(f"{rdir}/capture.pcapng"):
        rows = []
        for key, c in load_connections(f"{rdir}/capture.pcapng").items():
            if c["iface"] != "enp0s31f6" or not c["client"].startswith(PI_IP):
                continue
            for e in c["events"]:
                if e["type"] == "PUBLISH" and e["dir"] == "c2s" and e.get("seq") is not None:
                    rows.append((e["topic"], e["seq"], e["t"] / 1e9))
        nic = pd.DataFrame(rows, columns=["topic", "seq", "t_nic"]).drop_duplicates(["topic", "seq"])
        df = df.merge(nic, on=["topic", "seq"], how="left")
        df["pre_nic_ms"] = (df.t_nic - df.tp) * 1e3
        df["post_nic_ms"] = (df.t_rx_ns / 1e9 - df.t_nic) * 1e3

    # per episode checks
    used = set()
    res = []
    for i, (es, ee, n, mx) in enumerate(eps):
        m = [j for j, (a, b, _) in enumerate(scans) if abs(a - es) <= TOL_S and abs(b - ee) <= TOL_S]
        near = min(scans, key=lambda s: abs(s[0] - es)) if scans else None
        used.update(m)
        r = dict(ep=i, start=es, dur=ee - es, n_over=n, max_ms=mx,
                 matched=bool(m),
                 d_start=(near[0] - es) if near else np.nan, d_end=(near[1] - ee) if near else np.nan)
        for tag, (pg, _) in pings.items():
            w = pg[(pg.t_tx >= es - 1) & (pg.t_tx <= ee + 1)]
            r[f"{tag}_slow"] = int((w.rtt > THRESH_MS).sum())
            r[f"{tag}_max"] = w.rtt.max()
        win = df[(df.tp >= es) & (df.tp <= ee)]
        pre = df[(df.tp >= es - 5) & (df.tp < es)]
        r["lag_in"], r["lag_pre"] = win.sched_lag_ms.max(), pre.sched_lag_ms.max()
        r["lag_ok"] = r["lag_in"] <= r["lag_pre"] + 1.0
        if nic is not None:
            d = win[win.latency_ms > THRESH_MS]
            r["pre_nic_share"] = (d.pre_nic_ms.sum() / d.latency_ms.sum())
            r["post_nic_max"] = d.post_nic_ms.max()
            r["no_nic"] = int(d.t_nic.isna().sum())
        res.append(r)
    R = pd.DataFrame(res)
    if len(R):
        R["start"] = pd.to_datetime(R.start, unit="s", utc=True).dt.tz_convert("America/Denver").dt.strftime("%H:%M:%S.%f").str[:-3]
        pd.set_option("display.width", 250, "display.max_columns", 30)
        print(R.round(3).to_string(index=False))
        ok = R.matched & R.lag_ok
        if "pi_slow" in R:
            ok &= (R.pi_slow > 0) & (R.router_slow == 0)
        if "pre_nic_share" in R:
            ok &= R.pre_nic_share > 0.9
        print(f"  matched scans: {int(R.matched.sum())}/{len(R)}; all checks passed: {int(ok.sum())}/{len(R)}")
        # context for the lag check: max sched_lag in episode-length windows away from scans/episodes
        far = np.ones(len(df), bool)
        for a, b in [(e[0], e[1]) for e in eps] + [(s[0], s[1]) for s in scans]:
            far &= ~((df.tp >= a - 6) & (df.tp <= b + 1))
        bgl = df[far]
        wl = bgl.groupby(((bgl.tp - bgl.tp.min()) // 3.6).astype(int)).sched_lag_ms.max()
        print(f"  sched_lag context: max per 3.6 s window away from episodes/scans: p50 {wl.median():.2f}, "
              f"p90 {wl.quantile(.9):.2f}, max {wl.max():.2f} ms; share of windows >= each episode's lag_in: "
              + ", ".join(f"{100 * (wl >= x).mean():.0f}%" for x in R.lag_in))
    unmatched = [s for j, s in enumerate(scans) if j not in used]
    print(f"  scans with no episode: {len(unmatched)}" + "".join(
        f"\n    {pd.Timestamp(a, unit='s', tz='UTC').tz_convert('America/Denver'):%H:%M:%S}, dur {b - a:.3f} s, "
        f"max latency in window {df[(df.tp >= a - 1) & (df.tp <= b + 1)].latency_ms.max():.1f} ms"
        for a, b, _ in unmatched))
    print(f"  episodes with no scan: {int((~R.matched).sum()) if len(R) else 0}")

    # background, outside +-5 s of episodes and scans
    bad = np.zeros(len(df), bool)
    for a, b in [(e[0], e[1]) for e in eps] + [(s[0], s[1]) for s in scans]:
        bad |= (df.tp >= a - BG_EXCL_S) & (df.tp <= b + BG_EXCL_S)
    bg = df[~bad]
    print(f"  background latency (outside +-{BG_EXCL_S:.0f} s of episodes/scans): {pct(bg.latency_ms.dropna())}")
    for s in ("bmp280", "mpu6050", "ina219"):
        print(f"    {s:>8}: {pct(bg[bg.sensor == s].latency_ms.dropna())}")
    if nic is not None:
        print(f"    Pi publish -> NIC: {pct(bg.pre_nic_ms.dropna())}")
        print(f"    NIC -> logger:     {pct(bg.post_nic_ms.dropna())}")
    # drift over the run: 5-min blocks
    t0 = df.tp.min()
    blk = ((bg.tp - t0) // 300).astype(int)
    print("    by 5-min block, p50/p95/p99 ms: " + "; ".join(
        f"{k}: {g.latency_ms.median():.2f}/{g.latency_ms.quantile(.95):.2f}/{g.latency_ms.quantile(.99):.2f}"
        for k, g in bg.groupby(blk)))
    for tag, (pg, (sent, got)) in pings.items():
        pbad = np.zeros(len(pg), bool)
        for a, b in [(e[0], e[1]) for e in eps] + [(s[0], s[1]) for s in scans]:
            pbad |= (pg.t_tx >= a - BG_EXCL_S) & (pg.t_tx <= b + BG_EXCL_S)
        print(f"  ping {tag}: sent {sent}, received {got}; background RTT {pct(pg[~pbad].rtt)}")
    sysl = f"{rdir}/pi_side/system.log"
    if os.path.exists(sysl):
        f = [int(m.group(1)) // 1_000_000 for m in re.finditer(r"frequency\(48\)=(\d+)", open(sysl).read())]
        if f:
            vc = pd.Series(f).value_counts(normalize=True).sort_index()
            print("  Pi ARM clock samples (MHz: share): " + ", ".join(f"{k}: {100 * v:.0f}%" for k, v in vc.items()))
