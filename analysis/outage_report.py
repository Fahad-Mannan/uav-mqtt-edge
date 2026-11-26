#!/usr/bin/env python3
"""Report for bench outage runs (code/bench_outage.py; design in docs/bench_outage_2026-11-24.md).

Per run folder (run_field.py flight mode, one segment, plus outage.json):
  - messages sent (pi_log.csv), received unique (rx_all.csv, by topic + t_pub_ns), lost, duplicates
    (extra rows of the same message, and rows with the MQTT dup flag);
  - the same split by publish time: before / during / after the outage (t_on, t_off from outage.json),
    with paho rc 4 (not connected) counts and lost messages that had rc 0 (written to a dead socket);
  - publisher.out events relative to the cut (DISCONNECT, CONNECT, SOCKET_OPEN, DRAIN, FINISH);
  - detection = first DISCONNECT after t_on - t_on; reconnect = first CONNECT after t_off - t_off;
    first delivery = first t_rx after t_off - t_off; backlog flushed = last t_rx of a message published
    before t_off - t_off; max latency of messages published during the outage;
  - IMU (mpu6050) peak AoI: at each reception, t_rx - newest t_sample received before it; max over
    the segment (from 1 s after its start);
  - broker journal (journalctl -u mosquitto, run window - 10 s to + 90 s): "dropped" lines, and lines
    about the Pi's client (timeouts, disconnects, connects);
  - throttled values (pi_side/system.log) in the segment window; chrony LastRx/offset after t_off.
Clock note: Pi times (pi_log, publisher.out) are chrony-synced to the laptop. During the outage the
Pi gets no NTP replies and free-runs (drift ~ppm, so < 0.1 ms over 60 s).
Writes <run>/outage/report.{json,md}; with several folders also prints one summary table.
Usage: python analysis/outage_report.py data/bench_outage_2026-11-24/A_q1_o30 [more run folders]
"""
import glob, json, os, re, subprocess, sys
import numpy as np
import pandas as pd


def events(path):
    ev = []
    for line in open(path):
        m = re.match(r"(SOCKET_OPEN|CONNECT|DISCONNECT|DRAIN|FINISH)\b(.*?)\s*t=([\d.]+)\s*$", line.strip())
        if m:
            ev.append((m.group(1), m.group(2).strip(), float(m.group(3))))
    return ev


def journal(t0, t1, rdir):
    """Broker log lines in [t0, t1]. The lab broker logs to /var/log/mosquitto/mosquitto.log (mode 600,
    log_dest file), not the journal: a copy at <session>/mosquitto.log (lines '<epoch>: text') is used
    if present; otherwise journalctl -u mosquitto (empty for this broker)."""
    p = os.path.join(os.path.dirname(os.path.abspath(rdir)), "mosquitto.log")
    if os.path.exists(p):
        out = []
        for line in open(p, errors="replace"):
            m = re.match(r"(\d+(?:\.\d+)?): (.*)", line.rstrip("\n"))
            if m and t0 <= float(m.group(1)) <= t1:
                out.append(f"{float(m.group(1)) :.0f} {m.group(2)}")
        return out
    fmt = lambda t: "@%d" % int(t)
    r = subprocess.run(["journalctl", "-u", "mosquitto", "--no-pager", "-o", "short-precise",
                        "--since", fmt(t0), "--until", fmt(t1)], capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l and not l.startswith("--")]


def peak_aoi(imu, t_from):
    """imu: rows with t_rx, t_sample (s). Peak AoI at each reception after t_from."""
    d = imu.sort_values("t_rx")
    newest = np.maximum.accumulate(d.t_sample.values)
    prev = np.concatenate([[np.nan], newest[:-1]])
    pk = d.t_rx.values - prev
    ok = (d.t_rx.values >= t_from) & ~np.isnan(pk)
    if not ok.any():
        return np.nan, np.nan
    i = np.nanargmax(np.where(ok, pk, -np.inf))
    return float(pk[i]), float(d.t_rx.values[i])


def report(rdir):
    o = json.load(open(os.path.join(rdir, "outage.json")))
    ev0 = o["events"]
    t_on, t_off = ev0["t_on"], ev0["t_off"]
    seg = pd.read_csv(os.path.join(rdir, "segments.csv")).iloc[0]
    lab = seg.label
    pl = pd.read_csv(os.path.join(rdir, "pi_segments", lab, "pi_log.csv"))
    rx = pd.read_csv(os.path.join(rdir, "rx_all.csv"))
    rx_u = rx.sort_values("t_rx_ns").drop_duplicates(["topic", "t_pub_ns"])
    m = pl.merge(rx_u[["topic", "t_pub_ns", "t_rx_ns", "latency_ms"]], on=["topic", "t_pub_ns"], how="left")
    m["rcvd"] = m.t_rx_ns.notna()
    m["t_pub"], m["t_rx"], m["t_sample"] = m.t_pub_ns / 1e9, m.t_rx_ns / 1e9, m.t_sample_ns / 1e9
    m["phase"] = np.where(m.t_pub < t_on, "before", np.where(m.t_pub < t_off, "during", "after"))
    extra_rows = len(rx) - len(rx_u)
    phases = {}
    for ph in ("before", "during", "after"):
        g = m[m.phase == ph]
        phases[ph] = {"sent": len(g), "rcvd": int(g.rcvd.sum()), "lost": int((~g.rcvd).sum()),
                      "rc4": int((g.rc == 4).sum()), "lost_rc0": int(((~g.rcvd) & (g.rc == 0)).sum()),
                      "conn0": int((g.conn == 0).sum()),
                      "lat_p50": float(g.latency_ms.median()) if g.rcvd.any() else None,
                      "lat_max": float(g.latency_ms.max()) if g.rcvd.any() else None}
    ev = events(os.path.join(rdir, "pi_segments", lab, "publisher.out"))
    # the publisher's own DISCONNECT at the end of the run says "Normal disconnection"; not an outage event
    t_disc = next((t for k, d, t in ev if k == "DISCONNECT" and t >= t_on and "Normal" not in d), None)
    t_conn = next((t for k, _, t in ev if k == "CONNECT" and t_disc is not None and t >= t_disc), None)
    reconnected = t_disc is not None
    before_off = m[(m.t_pub < t_off) & m.rcvd]
    after_rx = m[m.rcvd & (m.t_rx > t_off)]
    dur = m[(m.phase == "during") & m.rcvd]
    imu = m[(m.topic.str.endswith("mpu6050")) & m.rcvd]
    pk, pk_t = peak_aoi(imu, seg.actual_start_unix + 1)
    drain = next((d for k, d, _ in ev if k == "DRAIN"), None)
    j = journal(seg.actual_start_unix - 10, seg.end_unix + 90, rdir)
    jl = lambda pat: [l for l in j if re.search(pat, l, re.I)]
    sysl = []
    p = os.path.join(rdir, "pi_side", "system.log")
    if os.path.exists(p):
        for line in open(p):
            mm = re.match(r"([\d.]+) throttled=(0x[0-9a-f]+)", line)
            if mm and seg.actual_start_unix <= float(mm.group(1)) <= seg.end_unix:
                sysl.append(mm.group(2))
    chr_after = []
    p = os.path.join(rdir, "pi_side", "chrony.log")
    if os.path.exists(p):
        for line in open(p):
            f = line.split()
            if len(f) > 7 and float(f[0]) >= t_off:
                try:
                    chr_after.append((float(f[0]) - t_off, int(f[6]), f[7]))
                except ValueError:
                    pass
    R = {"run": os.path.basename(rdir.rstrip("/")), "qos": int(seg.qos), "outage_s": round(t_off - t_on, 2),
         "outage_start_after_segment_s": round(t_on - seg.actual_start_unix, 2),
         "broker_limits": o.get("broker_limits"), "ping_during_ok": ev0.get("ping_during_ok"),
         "ping_after_ok": ev0.get("ping_after_ok"), "qdisc_clean_after": ev0.get("clean_after"),
         "sent": len(m), "rcvd_unique": int(m.rcvd.sum()), "lost": int((~m.rcvd).sum()),
         "duplicate_rows": int(extra_rows), "dup_flag_rows": int(rx.dup.sum()), "phases": phases,
         "publisher_events_rel_cut_s": [(k, d, round(t - t_on, 2)) for k, d, t in ev],
         "disconnect_after_cut_s": round(t_disc - t_on, 2) if reconnected else None,
         "reconnect_after_restore_s": round(t_conn - t_off, 2) if reconnected and t_conn else None,
         "first_rx_after_restore_s": round(after_rx.t_rx.min() - t_off, 2) if len(after_rx) else None,
         "backlog_flushed_after_restore_s": round(before_off.t_rx.max() - t_off, 2) if len(before_off) and before_off.t_rx.max() > t_off else None,
         "during_rcvd_max_latency_s": round(dur.latency_ms.max() / 1e3, 2) if len(dur) else None,
         "imu_peak_aoi_max_s": round(pk, 3), "imu_peak_aoi_at_rel_cut_s": round(pk_t - t_on, 2) if pk_t == pk_t else None,
         "drain": drain, "segment_note": None if pd.isna(seg.get("note")) else seg.get("note"),
         "segment_rc": int(seg.rc),
         "broker_dropped_lines": jl("dropped"), "broker_client_lines": jl(r"timeout|disconnect|new client|exceeded|closing|socket error|already connected"),
         "throttled": dict(pd.Series(sysl).value_counts()) if sysl else {},
         "chrony_after_restore": chr_after[:8]}
    out = os.path.join(rdir, "outage")
    os.makedirs(out, exist_ok=True)
    json.dump(R, open(os.path.join(out, "report.json"), "w"), indent=1, default=str)
    L = [f"# Outage run {R['run']} (QoS {R['qos']}, outage {R['outage_s']} s at +{R['outage_start_after_segment_s']} s)", "",
         f"Broker limits {R['broker_limits']}. Ping during cut answered: {R['ping_during_ok']}; after: {R['ping_after_ok']}; "
         f"qdisc clean after: {R['qdisc_clean_after']}.", "",
         f"Sent {R['sent']}, received unique {R['rcvd_unique']}, lost {R['lost']}, duplicate rows {R['duplicate_rows']} "
         f"(dup flag {R['dup_flag_rows']}).", "", "| phase | sent | rcvd | lost | rc 4 | lost with rc 0 | conn 0 | p50 ms | max ms |",
         "|---|---|---|---|---|---|---|---|---|"]
    for ph, g in phases.items():
        L.append(f"| {ph} | {g['sent']} | {g['rcvd']} | {g['lost']} | {g['rc4']} | {g['lost_rc0']} | {g['conn0']} | "
                 f"{g['lat_p50'] if g['lat_p50'] is None else round(g['lat_p50'], 2)} | "
                 f"{g['lat_max'] if g['lat_max'] is None else round(g['lat_max'], 1)} |")
    L += ["", f"Disconnect {R['disconnect_after_cut_s']} s after the cut; reconnect {R['reconnect_after_restore_s']} s "
          f"after the restore; first delivery {R['first_rx_after_restore_s']} s after; backlog flushed "
          f"{R['backlog_flushed_after_restore_s']} s after; max latency of messages published during the outage "
          f"{R['during_rcvd_max_latency_s']} s; IMU peak AoI max {R['imu_peak_aoi_max_s']} s "
          f"(at {R['imu_peak_aoi_at_rel_cut_s']} s after the cut). DRAIN: {R['drain']}. Segment note: {R['segment_note']}.",
          "", "Publisher events (s from the cut): " + "; ".join(f"{k} {d} {t:+.2f}" for k, d, t in R["publisher_events_rel_cut_s"]),
          "", f"Broker 'dropped' lines: {len(R['broker_dropped_lines'])}", *[f"    {l}" for l in R["broker_dropped_lines"][:10]],
          f"Broker client lines: {len(R['broker_client_lines'])}", *[f"    {l}" for l in R["broker_client_lines"][:20]],
          "", f"Throttled in the segment: {R['throttled']}. Chrony after the restore (s, LastRx, last sample): {R['chrony_after_restore']}"]
    open(os.path.join(out, "report.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L) + "\n")
    return R


def main():
    rows = []
    for rdir in sys.argv[1:]:
        R = report(rdir)
        d = R["phases"]["during"]
        rows.append({"run": R["run"], "qos": R["qos"], "outage_s": R["outage_s"],
                     "limits": "/".join(str(v) for v in (R["broker_limits"] or {}).values()),
                     "sent": R["sent"], "rcvd": R["rcvd_unique"], "lost": R["lost"], "dups": R["duplicate_rows"],
                     "lost_before/during/after": "/".join(str(R["phases"][p]["lost"]) for p in ("before", "during", "after")),
                     "rc4_during": d["rc4"], "disc_s": R["disconnect_after_cut_s"], "reconn_s": R["reconnect_after_restore_s"],
                     "flush_s": R["backlog_flushed_after_restore_s"], "max_lat_s": R["during_rcvd_max_latency_s"],
                     "imu_aoi_s": R["imu_peak_aoi_max_s"], "dropped": len(R["broker_dropped_lines"]),
                     "throttled": ",".join(f"{k}x{v}" for k, v in R["throttled"].items())})
    if len(rows) > 1:
        pd.set_option("display.width", 250)
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
