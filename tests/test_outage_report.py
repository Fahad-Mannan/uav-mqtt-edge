#!/usr/bin/env python3
"""Synthetic check of analysis/outage_report.py (no Pi, no broker, no network change).
Case 1: QoS 1, 30 s outage, no disconnect, backlog delivered 0.5 s after the restore.
Case 2: QoS 0, 60 s outage, DISCONNECT 45 s after the cut, CONNECT 1 s after the restore; messages
between the cut and the DISCONNECT are lost with rc 0, the rest of the outage rc 4; one duplicate row.
Run: python tests/test_outage_report.py"""
import json, os, subprocess, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name} {detail}")


def make(rdir, qos, outage, disc=None, conn_after=None):
    os.makedirs(os.path.join(rdir, "pi_segments", "s01", ), exist_ok=True)
    t0 = 1.6e9                                    # segment start
    t_on, t_off = t0 + 30, t0 + 30 + outage
    dur = 30 + outage + 90
    rows = []
    for k, (topic, hz) in enumerate([("uav/uav_01/mpu6050", 20), ("uav/uav_01/bmp280", 2), ("uav/uav_01/ina219", 2)]):
        for i in range(int(dur * hz)):
            tp = t0 + i / hz + 0.001 * k
            rc = 0
            if qos == 0 and disc is not None and t_on + disc <= tp < t_off + conn_after:
                rc = 4
            rows.append({"topic": topic, "seq": i, "t_sample_ns": int((tp - 0.002) * 1e9), "t_pub_ns": int(tp * 1e9),
                         "qos": qos, "bytes": 100, "payload": "{}", "rc": rc, "conn": int(rc == 0)})
    pl = pd.DataFrame(rows)
    pl.to_csv(os.path.join(rdir, "pi_segments", "s01", "pi_log.csv"), index=False)
    rx = []
    for r in pl.itertuples():
        tp = r.t_pub_ns / 1e9
        if t_on <= tp < t_off:
            if qos == 0:
                continue                            # lost (rc 0 before the DISCONNECT, rc 4 after)
            trx = t_off + 0.5 + (tp - t_on) * 0.001
        elif qos == 0 and t_off <= tp < t_off + conn_after:
            continue
        else:
            trx = tp + 0.005
        rx.append({"t_rx_ns": int(trx * 1e9), "topic": r.topic, "qos": qos, "dup": 0, "seq": r.seq,
                   "t_pub_ns": r.t_pub_ns, "latency_ms": (trx - tp) * 1e3, "bytes": 100})
    rx = pd.DataFrame(rx)
    rx = pd.concat([rx, rx.iloc[[10]]])            # one duplicate row
    rx.to_csv(os.path.join(rdir, "rx_all.csv"), index=False)
    ev = [f"SOCKET_OPEN nodelay=1 t={t0 - 0.1:.3f}", f"CONNECT rc=Success t={t0 - 0.05:.3f}"]
    if disc is not None:
        ev += [f"DISCONNECT rc=Keep alive timeout t={t_on + disc:.3f}", f"SOCKET_OPEN nodelay=1 t={t_off + conn_after - 0.01:.3f}",
               f"CONNECT rc=Success t={t_off + conn_after:.3f}"]
    if qos:
        ev.append(f"DRAIN acked=100 of 100 in 0.05 s t={t0 + dur + 0.05:.3f}")
    ev += [f"FINISH t={t0 + dur + 0.1:.3f}", f"DISCONNECT rc=Normal disconnection t={t0 + dur + 0.2:.3f}"]
    open(os.path.join(rdir, "pi_segments", "s01", "publisher.out"), "w").write("\n".join(ev) + "\n")
    pd.DataFrame([{"label": "s01", "qos": qos, "actual_start_unix": t0, "end_unix": t0 + dur + 1, "late_s": 0,
                   "rc": 0, "note": np.nan, "run_s": dur}]).to_csv(os.path.join(rdir, "segments.csv"), index=False)
    os.makedirs(os.path.join(rdir, "pi_side"), exist_ok=True)
    open(os.path.join(rdir, "pi_side", "system.log"), "w").write(f"{t0 + 5:.3f} throttled=0x0 temp=40.0'C\n")
    json.dump({"events": {"t_on": t_on, "t_off": t_off, "ping_during_ok": False, "ping_after_ok": True, "clean_after": True},
               "broker_limits": {"max_queued_messages": "0", "max_inflight_messages": "0"}},
              open(os.path.join(rdir, "outage.json"), "w"))
    return pl


tmp = tempfile.mkdtemp(prefix="outrep_")
r1, r2 = os.path.join(tmp, "q1_o30"), os.path.join(tmp, "q0_o60")
make(r1, 1, 30)
pl2 = make(r2, 0, 60, disc=45, conn_after=1)
r = subprocess.run([sys.executable, os.path.join(ROOT, "analysis", "outage_report.py"), r1, r2], capture_output=True, text=True)
print(r.stdout[-1500:], r.stderr[-1500:])
A = json.load(open(os.path.join(r1, "outage", "report.json")))
B = json.load(open(os.path.join(r2, "outage", "report.json")))
check("case 1: nothing lost, 1 duplicate row", A["lost"] == 0 and A["duplicate_rows"] == 1, f"{A['lost']} {A['duplicate_rows']}")
check("case 1: no disconnect / reconnect reported", A["disconnect_after_cut_s"] is None and A["reconnect_after_restore_s"] is None)
check("case 1: backlog flushed ~0.53 s after the restore", abs(A["backlog_flushed_after_restore_s"] - 0.53) < 0.02, str(A["backlog_flushed_after_restore_s"]))
check("case 1: max latency of outage messages ~30.5 s", abs(A["during_rcvd_max_latency_s"] - 30.5) < 0.05, str(A["during_rcvd_max_latency_s"]))
# fresh messages after the restore arrive (5 ms) before the backlog (0.5 s) here, so the peak is
# the first fresh IMU message: t_off + 0.05 + 0.005 - (newest pre-cut sample t_on - 0.05 - 0.002)
check("case 1: IMU peak AoI ~30.06 s", abs(A["imu_peak_aoi_max_s"] - 30.057) < 0.01, str(A["imu_peak_aoi_max_s"]))
d = B["phases"]["during"]
n_dur = 60 * 24
n_rc4_dur = 15 * 24
check("case 2: all outage messages lost", d["lost"] == n_dur, f"{d['lost']} of {n_dur}")
check("case 2: rc 4 / lost with rc 0 split at the DISCONNECT", d["rc4"] == n_rc4_dur and d["lost_rc0"] == n_dur - n_rc4_dur,
      f"rc4 {d['rc4']} rc0 {d['lost_rc0']}")
check("case 2: 1 s after the restore lost too (rc 4)", B["phases"]["after"]["lost"] == 24, str(B["phases"]["after"]["lost"]))
check("case 2: disconnect 45 s after the cut, reconnect 1 s after the restore",
      B["disconnect_after_cut_s"] == 45.0 and B["reconnect_after_restore_s"] == 1.0, f"{B['disconnect_after_cut_s']} {B['reconnect_after_restore_s']}")
check("case 2: IMU peak AoI ~61 s", abs(B["imu_peak_aoi_max_s"] - 61.0) < 0.1, str(B["imu_peak_aoi_max_s"]))
print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
