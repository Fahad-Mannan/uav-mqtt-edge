#!/usr/bin/env python3
"""Run a flight schedule of publisher segments back to back on the Pi (stdlib only).

Started detached by run_field.py --schedule before takeoff. Each segment starts at its planned
wall-clock time (Pi clock, chrony-synced), runs publish_multi_sensor.py for its duration in its
own folder, and is logged to segments.csv with planned and actual start/end and the exit code.
A segment that starts late (the previous one overran, e.g. a 30 s drain with the link down) runs only
until its planned end, so lateness never carries over to later segments; one with less than
MIN_SEG_S left is skipped. Both are noted in segments.csv (`run_s` = duration actually requested).
A segment that can't connect (link down) still publishes (the publisher waits --connect-wait-s,
then publishes anyway). MQTT_PASSWORD comes from the environment.

Usage: flight_launcher.py --schedule schedule.json --outdir DIR [--python PY] [--publisher PATH]
"""
import argparse, csv, json, os, signal, subprocess, sys, time

p = argparse.ArgumentParser()
p.add_argument("--schedule", required=True)
p.add_argument("--outdir", required=True)
p.add_argument("--python", default=sys.executable)
p.add_argument("--publisher", default=os.path.expanduser("~/mqtt_uav_test/publish_multi_sensor.py"))
a = p.parse_args()

sched = json.load(open(a.schedule))
os.makedirs(a.outdir, exist_ok=True)
log_path = os.path.join(a.outdir, "segments.csv")
cols = ["label", "point", "qos", "duration_s", "planned_start_unix", "actual_start_unix", "end_unix",
        "late_s", "rc", "note", "run_s"]
MIN_SEG_S = 5.0          # a late segment with less than this left before its planned end is skipped
LATE_TOL_S = 0.5         # later than this: shorten to the planned end
new = not os.path.exists(log_path)
fh = open(log_path, "a", newline="")
w = csv.writer(fh)
if new:
    w.writerow(cols)
    fh.flush()
child = [None]
stop = [False]

def on_term(signum, frame):
    stop[0] = True
    if child[0] and child[0].poll() is None:
        child[0].send_signal(signal.SIGINT)        # publisher handles KeyboardInterrupt cleanly

signal.signal(signal.SIGTERM, on_term)
signal.signal(signal.SIGINT, on_term)
print(f"launcher start {time.time():.3f}, {len(sched['segments'])} segments", flush=True)

for seg in sched["segments"]:
    if stop[0]:
        break
    wait = seg["start_unix"] - time.time()
    while wait > 0 and not stop[0]:
        time.sleep(min(wait, 1.0))
        wait = seg["start_unix"] - time.time()
    if stop[0]:
        break
    sdir = os.path.join(a.outdir, seg["label"])
    os.makedirs(sdir, exist_ok=True)
    now = time.time()
    run_s, note = seg["duration_s"], ""
    if now - seg["start_unix"] > LATE_TOL_S:
        run_s = round(seg["end_unix"] - now, 3)
        if run_s < MIN_SEG_S:
            w.writerow([seg["label"], seg["point"], seg["qos"], seg["duration_s"], f"{seg['start_unix']:.3f}",
                        "", "", f"{now - seg['start_unix']:.3f}", "", f"skipped: late, {run_s:.1f} s left", 0])
            fh.flush()
            print(f"{seg['label']}: skipped (late, {run_s:.1f} s left)", flush=True)
            continue
        note = f"shortened to {run_s:.1f} s (late)"
    cmd = [a.python, a.publisher, "--duration", str(run_s), "--qos", str(seg["qos"]),
           "--imu-hz", str(sched["imu_hz"]), "--nodelay", str(sched["nodelay"]),
           "--log", os.path.join(sdir, "pi_log.csv")]
    t_start = time.time()
    with open(os.path.join(sdir, "publisher.out"), "w") as out:
        try:
            child[0] = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        cwd=os.path.dirname(a.publisher))
            rc = child[0].wait(timeout=run_s + 60)
        except subprocess.TimeoutExpired:
            child[0].kill()
            rc, note = child[0].wait(), (note + " timeout").strip()
        except OSError as e:
            rc, note = -1, (note + f" start failed: {e}").strip()
    t_end = time.time()
    if stop[0]:
        note = (note + " stopped").strip()
    w.writerow([seg["label"], seg["point"], seg["qos"], seg["duration_s"], f"{seg['start_unix']:.3f}",
                f"{t_start:.3f}", f"{t_end:.3f}", f"{t_start - seg['start_unix']:.3f}", rc, note, run_s])
    fh.flush()
    print(f"{seg['label']}: rc {rc}, {t_end - t_start:.1f} s {note}", flush=True)
print(f"launcher end {time.time():.3f}", flush=True)
