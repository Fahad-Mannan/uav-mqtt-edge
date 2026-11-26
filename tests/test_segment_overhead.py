#!/usr/bin/env python3
"""Interleaved-QoS flight segments on the laptop: per-segment overhead, late-segment handling, pooling.

No Pi. A private Mosquitto (127.0.0.1, spare port, lab-like config) and the real
code/pi/flight_launcher.py running the real code/pi/publish_multi_sensor.py (--fake-sensors, through a
small wrapper that adds --broker/--port) and the real code/logger.py.

A: 6 segments qos0,qos1,qos2,qos0,qos1,qos2 x 6 s, gap 3 s. Per segment: launcher start -> socket
   open, publish window, end of publishing -> process exit, total wall time minus the requested
   duration (= overhead), late_s. Then flight_lib.split and a per-QoS pooling check (every message
   of a QoS lands in a segment of that QoS; per-QoS sums = sent).
B: 4 segments qos1,qos2,qos0,qos1 x 12 s, gap 3 s; the broker is stopped 3 s into the first segment
   and restarted 14 s later, so its drain waits for the reconnect and it overruns. Checks: segment 2
   starts late and is shortened to its planned end (or skipped), segments 3-4 start on time, and the
   first segment's QoS 1 messages are all acknowledged (DRAIN line).
Run: python tests/test_segment_overhead.py   (~2 min)
"""
import json, os, re, shutil, signal, socket, subprocess, sys, tempfile, time
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "code"))
import flight_lib as F

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name} {detail}")


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def start_broker(tmp, port):
    conf = os.path.join(tmp, "broker.conf")
    with open(conf, "w") as fh:
        fh.write(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\nset_tcp_nodelay true\n"
                 "max_queued_messages 0\nmax_inflight_messages 0\n")
    proc = subprocess.Popen([shutil.which("mosquitto") or "/usr/sbin/mosquitto", "-c", conf],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return proc
        except OSError:
            time.sleep(0.1)
    raise SystemExit("private broker did not start")


def run_launcher(tmp, name, spec, port, delay=2.0, gap=3.0, during=None):
    outdir = os.path.join(tmp, name)
    os.makedirs(outdir)
    sched = F.build(spec, ["ob"], None, time.time(), delay, gap, 30, 20.0, 1)
    json.dump(sched, open(os.path.join(outdir, "schedule.json"), "w"))
    wrapper = os.path.join(tmp, "pub_wrapper.py")
    with open(wrapper, "w") as fh:
        fh.write("import os, sys\n"
                 f"os.execv(sys.executable, [sys.executable, {os.path.join(ROOT, 'code', 'pi', 'publish_multi_sensor.py')!r},"
                 f" '--fake-sensors', '--broker', '127.0.0.1', '--port', '{port}'] + sys.argv[1:])\n")
    env = dict(os.environ, MQTT_PASSWORD="x")
    lp = subprocess.Popen([sys.executable, os.path.join(ROOT, "code", "pi", "flight_launcher.py"), "--schedule",
                           os.path.join(outdir, "schedule.json"), "--outdir", outdir, "--python", sys.executable,
                           "--publisher", wrapper], env=env, stdout=subprocess.PIPE, text=True)
    if during:
        during(sched)
    out, _ = lp.communicate(timeout=300)
    print(out.strip())
    return sched, outdir, pd.read_csv(os.path.join(outdir, "segments.csv"))


def events(outdir, label):
    ev = {}
    for line in open(os.path.join(outdir, label, "publisher.out")):
        m = re.match(r"(\w+).* t=([\d.]+)$", line.strip())
        if m:
            ev.setdefault(m.group(1), float(m.group(2)))
        m = re.match(r"DRAIN acked=(\d+) of (\d+)", line)
        if m:
            ev["acked"], ev["to_ack"] = int(m.group(1)), int(m.group(2))
    return ev


tmp = tempfile.mkdtemp(prefix="segov_")
port = free_port()
broker = start_broker(tmp, port)
env = dict(os.environ, MQTT_PASSWORD="x")
try:
    # ------------------------------------------------------------ A: overhead and pooling
    rx_path = os.path.join(tmp, "A_rx_all.csv")
    logger = subprocess.Popen([sys.executable, os.path.join(ROOT, "code", "logger.py"), "--broker", "127.0.0.1",
                               "--port", str(port), "--qos", "2", "--out", rx_path, "--nodelay", "1"],
                              env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    sched, outA, segA = run_launcher(tmp, "A", "qos0:6,qos1:6,qos2:6,qos0:6,qos1:6,qos2:6", port)
    time.sleep(1.0)
    logger.send_signal(signal.SIGINT)
    logger.wait(timeout=10)
    rows = []
    for _, s in segA.iterrows():
        ev = events(outA, s.label)
        pl = pd.read_csv(os.path.join(outA, s.label, "pi_log.csv"))
        first, last = pl.t_pub_ns.min() / 1e9, pl.t_pub_ns.max() / 1e9
        rows.append({"label": s.label, "qos": s.qos, "late_s": s.late_s, "run_s": s.run_s,
                     "start_to_socket_s": ev["SOCKET_OPEN"] - s.actual_start_unix,
                     "start_to_first_pub_s": first - s.actual_start_unix,
                     "last_pub_to_exit_s": s.end_unix - last,
                     "wall_s": s.end_unix - s.actual_start_unix,
                     "overhead_s": s.end_unix - s.actual_start_unix - s.run_s,
                     "no_data_before_next_s": None})
    for i in range(len(rows) - 1):
        nxt = pd.read_csv(os.path.join(outA, rows[i + 1]["label"], "pi_log.csv")).t_pub_ns.min() / 1e9
        cur = pd.read_csv(os.path.join(outA, rows[i]["label"], "pi_log.csv")).t_pub_ns.max() / 1e9
        rows[i]["no_data_before_next_s"] = nxt - cur
    R = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print("\nA: per-segment timing on the laptop (s)")
    print(R.round(3).to_string(index=False))
    check("A: every segment started within 0.2 s of plan", (segA.late_s.abs() < 0.2).all(), str(segA.late_s.tolist()))
    check("A: no segment shortened or skipped", segA.note.isna().all(), str(segA.note.tolist()))
    for q in (0, 1, 2):
        ov = R[R.qos == q].overhead_s
        print(f"A: overhead QoS {q}: {ov.min():.2f}-{ov.max():.2f} s")
    check("A: overhead below the 3 s gap at every QoS", (R.overhead_s < 3.0).all())

    # split and pooling by QoS
    fdir = os.path.join(tmp, "flightA")
    os.makedirs(os.path.join(fdir, "pi_segments"))
    for lab in segA.label:
        shutil.copytree(os.path.join(outA, lab), os.path.join(fdir, "pi_segments", lab))
    shutil.copy(os.path.join(outA, "segments.csv"), fdir)
    shutil.copy(rx_path, os.path.join(fdir, "rx_all.csv"))
    made = F.split(fdir, {"label": "flightA", "schedule": sched})
    check("A: split made one folder per segment", len(made) == 6, str(made))
    rx = pd.read_csv(rx_path)
    sent = pd.concat([pd.read_csv(os.path.join(outA, l, "pi_log.csv")) for l in segA.label])
    per_q_sent = sent.groupby("qos").size().to_dict()
    per_q_split = {}
    for lab in made:
        d = pd.read_csv(os.path.join(fdir, lab, "rx.csv"))
        q = json.load(open(os.path.join(fdir, lab, "meta.json")))["qos"]
        check(f"A: {lab}: every message in its rx.csv has QoS {q}", (d.qos == q).all() and len(d) > 0, f"n={len(d)}")
        per_q_split[q] = per_q_split.get(q, 0) + len(d)
    check("A: per-QoS pooled rx = sent (nothing lost, nothing in the wrong QoS)",
          per_q_split == per_q_sent, f"split {per_q_split} sent {per_q_sent}")
    check("A: logger got every message once", len(rx.drop_duplicates(['topic', 't_pub_ns'])) == len(sent),
          f"{len(rx)} rows, {len(sent)} sent")

    # ------------------------------------------------------------ B: overrun -> next segment shortened
    def outage(sched):
        global broker
        s0 = sched["segments"][0]["start_unix"]
        time.sleep(max(0, s0 + 3 - time.time()))
        broker.terminate(); broker.wait()
        t_down = time.time()
        time.sleep(14)
        broker = start_broker(tmp, port)
        print(f"B: broker down {t_down - s0:.1f}-{time.time() - s0:.1f} s after the first segment's start")
    schedB, outB, segB = run_launcher(tmp, "B", "qos1:12,qos2:12,qos0:12,qos1:12", port, during=outage)
    print("\nB: segments.csv")
    print(segB[["label", "qos", "late_s", "run_s", "note", "rc"]].to_string(index=False))
    ev0 = events(outB, segB.label[0])
    check("B: first segment (QoS 1): every message acknowledged after the reconnect",
          ev0.get("acked") == ev0.get("to_ack") and ev0.get("to_ack", 0) > 0, f"{ev0.get('acked')} of {ev0.get('to_ack')}")
    over = segB.end_unix[0] - (schedB["segments"][0]["end_unix"])
    print(f"B: first segment ended {over:.1f} s after its planned end")
    n1 = str(segB.note[1])
    check("B: second segment late, then shortened to its planned end or skipped",
          segB.late_s[1] > 0.5 and ("shortened" in n1 or "skipped" in n1), f"late {segB.late_s[1]:.1f} s, {n1}")
    if "shortened" in n1:
        check("B: shortened segment ended near its planned end",
              abs(segB.end_unix[1] - schedB["segments"][1]["end_unix"]) < 3, f"{segB.end_unix[1] - schedB['segments'][1]['end_unix']:+.1f} s")
    check("B: segments 3 and 4 started on time (lateness did not carry over)",
          (segB.late_s[2:].abs() < 0.2).all(), str(segB.late_s[2:].tolist()))
finally:
    broker.terminate()
print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
