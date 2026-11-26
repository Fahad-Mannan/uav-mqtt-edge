#!/usr/bin/env python3
"""Local end-to-end check of flight mode, no Pi and no MQTT:
schedule -> timetable -> code/pi/flight_launcher.py with tests/fake_publisher.py (real time,
~20 s) -> synthetic laptop rx_all.csv (2 messages dropped, 1.5 ms latency) -> flight_lib.split
-> analysis/metrics.py on the segment folders (PDR, distance grouping, clock flag).
Run: python tests/test_flight.py [workdir]"""
import json, os, shutil, subprocess, sys, tempfile, time
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "code"))
import flight_lib as F

work = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="flight_test_")
fdir = os.path.join(work, "flight_test", "f1")
shutil.rmtree(os.path.join(work, "flight_test"), ignore_errors=True)
pi_out = os.path.join(work, "pi_out")
shutil.rmtree(pi_out, ignore_errors=True)
os.makedirs(fdir)
fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name} {detail}")

sched = F.build("qos0:3,qos1:3", ["h10", "h30"], [10.0, 30.0], time.time(), 2, 1, 2, 20.0, 1)
tt = F.timetable(sched)
print(tt)
check("timetable ends with the flight-plan line, not 'land after that'",
      "Follow the flight plan (RTL at the planned time); last segment ends" in tt and "land after that" not in tt)
starts = [s["start_unix"] - sched["launch_unix"] for s in sched["segments"]]
check("planned starts (delay 2, gap 1, move 2)", [round(x, 3) for x in starts] == [2, 6, 11, 15], str(starts))

# one spec per point ('/'): f2 of 2026-11-23, order reversed at the second point
s2 = F.build("qos0:40,qos1:40,qos2:40/qos2:40,qos1:40,qos0:40", ["d050", "d150"], [50.0, 150.0], 1000.0,
             60, 5, 30, 20.0, 1)
got = [(x["label"], x["qos"], x["start_unix"] - 1000.0, x["distance_m"]) for x in s2["segments"]]
want = [("s01_d050_qos0", 0, 60, 50.0), ("s02_d050_qos1", 1, 105, 50.0), ("s03_d050_qos2", 2, 150, 50.0),
        ("s04_d150_qos2", 2, 220, 150.0), ("s05_d150_qos1", 1, 265, 150.0), ("s06_d150_qos0", 0, 310, 150.0)]
check("per-point specs: order, labels, starts, distances", got == want, str(got))
check("per-point specs: total 350 s", s2["end_unix"] - 1000.0 == 350, str(s2["end_unix"] - 1000.0))
same = F.build("qos0:40,qos1:40,qos2:40", ["d050", "d150"], [50.0, 150.0], 1000.0, 60, 5, 30, 20.0, 1)
check("one spec without '/' still repeats at every point",
      [x["qos"] for x in same["segments"]] == [0, 1, 2, 0, 1, 2])
s3 = F.build("qos1:10/qos0:20,qos2:5", ["a", "b"], None, 0.0, 0, 1, 3, 20.0, 1)
check("per-point specs: different lengths",
      [(x["qos"], x["start_unix"], x["end_unix"]) for x in s3["segments"]] == [(1, 0, 10), (0, 13, 33), (2, 34, 39)],
      str([(x["qos"], x["start_unix"], x["end_unix"]) for x in s3["segments"]]))
for bad in ("qos0:40/qos1:40/qos2:40", "qos0:40/", "qos0:40/qos3:40"):
    try:
        F.build(bad, ["d050", "d150"], None, 0.0, 0, 1, 3, 20.0, 1)
        check(f"bad spec {bad!r} refused", False)
    except ValueError as e:
        check(f"bad spec {bad!r} refused", True, f"({e})")

os.makedirs(pi_out)
json.dump(sched, open(os.path.join(pi_out, "schedule.json"), "w"))
r = subprocess.run([sys.executable, os.path.join(ROOT, "code", "pi", "flight_launcher.py"),
                    "--schedule", os.path.join(pi_out, "schedule.json"), "--outdir", pi_out,
                    "--python", sys.executable, "--publisher", os.path.join(ROOT, "tests", "fake_publisher.py")],
                   capture_output=True, text=True, timeout=120)
print(r.stdout.strip())
segs = pd.read_csv(os.path.join(pi_out, "segments.csv"))
check("launcher ran 4 segments, rc 0", len(segs) == 4 and (segs.rc == 0).all())
check("each segment started within 0.2 s of plan", (segs.late_s.abs() < 0.2).all(), str(segs.late_s.round(3).tolist()))

# laptop side: rx_all.csv from every pi_log, 1.5 ms latency, two messages dropped in segment 2
rows = []
for lab in segs.label:
    pl = pd.read_csv(os.path.join(pi_out, lab, "pi_log.csv"))
    if lab == segs.label[1]:
        pl = pl.drop(index=[5, 6])
    t_rx = pl.t_pub_ns + 1_500_000
    rows.append(pd.DataFrame({"t_rx_ns": t_rx, "topic": pl.topic, "qos": pl.qos, "dup": 0, "seq": pl.seq,
                              "t_pub_ns": pl.t_pub_ns, "latency_ms": 1.5, "bytes": pl.bytes}))
pd.concat(rows).sort_values("t_rx_ns").to_csv(os.path.join(fdir, "rx_all.csv"), index=False)
shutil.copy(os.path.join(pi_out, "segments.csv"), fdir)
os.makedirs(os.path.join(fdir, "pi_segments"))
for lab in segs.label:
    shutil.copytree(os.path.join(pi_out, lab), os.path.join(fdir, "pi_segments", lab))
# clock: stalled after the flight, and one stalled sample during segment 3
open(os.path.join(fdir, "chrony_after.txt"), "w").write(
    "System time     : 0.000080000 seconds fast of NTP time\n"
    "^* 192.168.1.4                   4   2   377   160   +144us[ +179us] +/-   22ms\n")
os.makedirs(os.path.join(fdir, "pi_side"))
t3 = segs.actual_start_unix[2] + 1
t1s = segs.actual_start_unix[0] + 1
open(os.path.join(fdir, "pi_side", "chrony.log"), "w").write(
    # normal over Wi-Fi: LastRx 31 s in segment 1 (must not flag; stall threshold 60 s)
    f"{t1s:.3f} ^* 192.168.1.4                   4   2   377    31   +1us[ +1us] +/-   22ms | "
    f"System time     : 0.000020000 seconds slow of NTP time\n"
    # stalled: LastRx 90 s, 1 s into segment 3, with a 2.5 ms offset
    f"{t3:.3f} ^* 192.168.1.4                   4   2   377    90   +1us[ +1us] +/-   22ms | "
    f"System time     : 0.002500000 seconds slow of NTP time\n")
flight = {"label": "f1", "session": "flight_test", "imu_hz": 20.0, "bmp_hz": 2.0, "ina_hz": 2.0,
          "nodelay": 1, "schedule": sched}
json.dump(flight, open(os.path.join(fdir, "flight.json"), "w"))

made = F.split(fdir, flight)
check("split made 4 segment folders", len(made) == 4, str(made))
for lab in made:
    m = json.load(open(os.path.join(fdir, lab, "meta.json")))
    n_rx = len(pd.read_csv(os.path.join(fdir, lab, "rx.csv")))
    n_pl = len(pd.read_csv(os.path.join(fdir, lab, "pi_log.csv")))
    want = n_pl - (2 if lab == made[1] else 0)
    check(f"{lab}: rx rows {n_rx} = sent {n_pl} - dropped", n_rx == want, f"(qos {m['qos']}, {m['distance_m']} m)")

r = subprocess.run([sys.executable, os.path.join(ROOT, "analysis", "metrics.py"), os.path.join(work, "flight_test")],
                   capture_output=True, text=True, timeout=120)
if r.returncode:
    print(r.stderr)
R = pd.read_csv(os.path.join(work, "flight_test", "metrics_runs.csv")).sort_values("run")
P = pd.read_csv(os.path.join(work, "flight_test", "metrics_pooled.csv"))
check("metrics found the 4 segments, not the flight folder", len(R) == 4, str(R.run.tolist()))
check("PDR 100% except segment 2", list(R.pdr_pct.round(3) < 100) == [False, True, False, False],
      str(R.pdr_pct.round(3).tolist()))
check("latency p50 1.5 ms", (R.lat_p50_ms.round(3) == 1.5).all())
check("pooled per distance and QoS: 4 groups", (P.group == "distance_qos").sum() == 4)
flags = R.clock_flag.fillna("")
check("all segments flagged by chrony_after LastRx 160 s", flags.str.contains("chrony_after LastRx 160").all())
# the sample (LastRx 90 s) taken 1 s into segment 3 means no chrony update in the 90 s before:
# segments 1-3 overlap that gap; segment 4 starts later. Its 2.5 ms offset was taken in segment 3.
# The 31 s sample in segment 1 is normal (below the 60 s stall threshold) and flags nothing.
check("LastRx stall flags segments 1-3 (overlap the gap)", list(flags.str.contains("during run LastRx up to 90")) == [True, True, True, False],
      str(flags.tolist()))
check("no flag says 31 s", not flags.str.contains("LastRx up to 31").any())
check("in-run offset flags only segment 3", list(flags.str.contains("during run \\|offset\\|")) == [False, False, True, False])
check("nominal Eq. 8 rate uses 20/2/2 Hz", (R.mpu6050_nominal_hz == 20).all())
print(f"work dir: {work}")
sys.exit(1 if fails else 0)
