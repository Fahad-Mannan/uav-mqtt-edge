#!/usr/bin/env python3
"""One field (or bench baseline) run per call, robust to a lost link.

The publisher and side_log.sh are started detached on the Pi (setsid nohup) with a fixed
duration, so they finish on their own even if the laptop loses the Pi. The laptop logger runs
for the same window. Afterwards the Pi's logs are collected, retrying while the link is down;
if that still fails, re-run later with --collect-only.

Before each run, a power gate reads vcgencmd get_throttled 5 times over 10 s and refuses to start
if any reading has bit 0x1 (under-voltage now) or 0x10000 (under-voltage since boot; clears only on
reboot). Then a chrony gate takes 13 readings over 60 s and refuses to start (printing the
restart command) unless, in every reading, the laptop is the selected source, LastRx <= --stall-lastrx
(60 s) and |offset| <= --max-offset-ms (1 ms); at least one reading has LastRx <= --fresh-lastrx
(10 s); and chronyd accepted a new sample during the readings (LastRx drops, or the "Last sample"
offset changes). LastRx of 15-30 s is normal over Wi-Fi; a stall grows past 60 s, and starts as a
steady rise from a low value with the last sample frozen.

Layout: data/<session>/<label>/ with rx.csv, pi_log.csv, pi_side/, publisher.out, meta.json,
chrony_*.txt, wifi_*.txt, station_*.txt (+ ping_*.txt, capture.pcapng if asked). On the Pi:
~/mqtt_uav_test/field/<session>__<label>/.

Examples:
  python code/run_field.py --session field_2026-12-01 --label d050_qos1_r1 --qos 1 \
      --duration 300 --distance-m 50 --pi-height-m 1.5 --router-height-m 2.0 --notes "LOS, mast"
  python code/run_field.py --session field_2026-12-01 --label d050_qos1_r1 --collect-only
  python code/run_field.py --session test --label dry --qos 1 --duration 60 --dry-run
"""
import argparse, getpass, importlib.metadata, json, os, re, shutil, signal, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import campaign_lib as L

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("--session", required=True, help="folder under data/, e.g. field_2026-12-01")
p.add_argument("--label", required=True, help="run label, e.g. d050_qos1_r1 ([A-Za-z0-9_.-])")
p.add_argument("--notes", default="", help="free text: site, LOS, weather, ...")
p.add_argument("--distance-m", type=float, default=None)
p.add_argument("--pi-height-m", type=float, default=None, help="Pi antenna height above ground")
p.add_argument("--router-height-m", type=float, default=None, help="router antenna height above ground")
p.add_argument("--qos", type=int, default=1, choices=[0, 1, 2])
p.add_argument("--duration", type=int, default=300, help="publisher duration, s")
p.add_argument("--imu-hz", type=float, default=20.0)
p.add_argument("--nodelay", type=int, default=1, choices=[0, 1], help="TCP_NODELAY on publisher and logger")
p.add_argument("--sidelog", type=int, default=1, choices=[0, 1])
p.add_argument("--stadump", type=float, default=1.0, help="station dump interval, s (0 = off)")
p.add_argument("--ping", type=float, default=0, help="ping rate, Hz, to the Pi and the router (0 = off)")
p.add_argument("--pcap", type=int, default=0, choices=[0, 1])
p.add_argument("--tail-s", type=float, default=15.0,
               help="keep the logger running this long after the publisher's nominal end")
p.add_argument("--stall-lastrx", type=float, default=L.STALL_LASTRX_S, help="chrony LastRx above this = stalled, s")
p.add_argument("--fresh-lastrx", type=float, default=L.FRESH_LASTRX_S,
               help="the start gate needs one reading with LastRx at or below this, s")
p.add_argument("--max-offset-ms", type=float, default=L.MAX_OFFSET_MS)
p.add_argument("--retries", type=int, default=60, help="collection attempts")
p.add_argument("--retry-wait", type=float, default=10.0, help="s between collection attempts")
p.add_argument("--collect-only", action="store_true", help="only collect the Pi logs of an earlier run")
p.add_argument("--overwrite", action="store_true", help="allow reusing an existing run folder")
p.add_argument("--dry-run", action="store_true",
               help="print every remote command instead of running it; no SSH, no logger")
p.add_argument("--dry-run-throttled", default="0x0,0x0,0x0,0x0,0x0",
               help="dry run only: get_throttled values the power gate sees, e.g. '0x0,0x50005,0x0,0x0,0x0'")
f = p.add_argument_group("flight mode (--schedule): one detached launcher runs all segments")
f.add_argument("--schedule", default=None,
               help="segments per hover point, e.g. 'qos0:120,qos1:120,qos2:120' (QoS:seconds), the same at "
                    "every point; or one spec per point separated by '/', e.g. "
                    "'qos0:40,qos1:40,qos2:40/qos2:40,qos1:40,qos0:40'")
f.add_argument("--points", default="p1", help="hover point labels, e.g. 'h10,h30,h60'")
f.add_argument("--point-distances", default=None, help="distance in m per point, e.g. '10,30,60'")
f.add_argument("--start-delay-s", type=float, default=120, help="launch -> first segment (take-off)")
f.add_argument("--gap-s", type=float, default=5, help="gap between segments at one point")
f.add_argument("--move-s", type=float, default=30, help="gap between the last segment at one point and the next point")
a = p.parse_args()

if not re.fullmatch(r"[A-Za-z0-9_.-]+", a.label) or not re.fullmatch(r"[A-Za-z0-9_.-]+", a.session):
    sys.exit("--session and --label may only contain letters, digits, '_', '.', '-'")

rdir = os.path.join(L.HOME, "data", a.session, a.label)
remote = f"{L.PI_DIR}/field/{a.session}__{a.label}"          # relative to the Pi user's home
FLIGHT = bool(a.schedule) or (a.collect_only and os.path.exists(os.path.join(rdir, "flight.json")))
# a flight folder holds flight.json (not meta.json) so metrics.py treats only its segments as runs
meta_path = os.path.join(rdir, "flight.json" if FLIGHT else "meta.json")
if FLIGHT and not a.collect_only:
    import flight_lib as F
    points = [x.strip() for x in a.points.split(",") if x.strip()]
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", x) for x in points):
        sys.exit("--points labels may only contain letters, digits, '_', '.', '-'")
    distances = [float(x) for x in a.point_distances.split(",")] if a.point_distances else None
    try:                                                      # fail early on a bad spec
        F.parse_specs(a.schedule, len(points))
    except ValueError as e:
        sys.exit(f"--schedule: {e}")

# ---------------------------------------------------------------- remote access (or dry run)
CANNED = {   # dry-run answers, shaped like the real output (first matching key wins)
    "=== THROTTLED": "".join(f"throttled={x}\n=== THROTTLED\n" for x in a.dry_run_throttled.split(",")),
    "=== READING": "".join(  # gate readings: LastRx 24, 1, 6, ... (normal over Wi-Fi), 13 readings
        f"^* 192.168.1.4  4   2   377    {x}   +12us[  +16us] +/-   22ms\n"
        "System time     : 0.000080802 seconds fast of NTP time\nUpdate interval : 20.2 seconds\n=== READING\n"
        for x in (24, 1, 6, 11, 16, 21, 26, 2, 7, 12, 17, 22, 27)),
    "true": "",
    "chronyc -n sources": "MS Name/IP address  Stratum Poll Reach LastRx Last sample\n"
                          "^* 192.168.1.4  4   2   377     2   +12us[  +16us] +/-   22ms\n",
    "chronyc tracking": "System time     : 0.000080802 seconds fast of NTP time\n"
                        "Last offset     : +0.000039085 seconds\n",
    "setsid": "12345",
    "kill -0": "",
}

def pi(cmd, stdin=None, timeout=None, connect_timeout=10):
    if a.dry_run:
        shown = cmd if stdin is None else f"{cmd}   [stdin: password]"
        print(f"  [dry-run ssh] {shown}")
        out = next((v for k, v in CANNED.items() if k in cmd), "")
        return subprocess.CompletedProcess(cmd, 0, out, "")
    return L.pi(cmd, stdin, timeout, connect_timeout)

def scp(src, dst, recursive=False):
    cmd = ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"] + (["-r"] if recursive else []) + [src, dst]
    if a.dry_run:
        print(f"  [dry-run] {' '.join(cmd)}")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return L.run(cmd)

def local(cmd_list, **kw):
    if a.dry_run:
        print(f"  [dry-run local] {' '.join(cmd_list)}")
        return None
    return subprocess.Popen(cmd_list, **kw)

def write_meta(meta):
    if a.dry_run:
        print(f"  [dry-run] write {meta_path}: keys {sorted(meta)}")
        return
    L.save(meta_path, json.dumps(meta, indent=2))

def pi_status(tag):
    for name, cmd in [("chrony", "chronyc tracking; chronyc -n sources"),
                      ("wifi", "/usr/sbin/iw dev wlan0 link"),
                      ("station", "/usr/sbin/iw dev wlan0 get power_save; /usr/sbin/iw dev wlan0 station dump")]:
        r = pi(cmd)
        if not a.dry_run:
            L.save(os.path.join(rdir, f"{name}_{tag}.txt"), r.stdout)

def power():
    return {"laptop": L.laptop_power(), "pi": L.parse_pi_power(pi(L.PI_POWER_CMD).stdout)}

# ---------------------------------------------------------------- collection
def arrange(tmp, meta):
    """Move the copied Pi folder into place: single run -> pi_log.csv, publisher.out, pi_side/;
    flight -> segments.csv, launcher.out, pi_side/, pi_segments/<label>/."""
    moves = [("side", "pi_side")]
    moves += ([("segments.csv", "segments.csv"), ("launcher.out", "launcher.out")] if FLIGHT
              else [("pi_log.csv", "pi_log.csv"), ("publisher.out", "publisher.out")])
    for name, dst in moves:
        src = os.path.join(tmp, name)
        if os.path.exists(src):
            if os.path.isdir(os.path.join(rdir, dst)):
                shutil.rmtree(os.path.join(rdir, dst))
            os.replace(src, os.path.join(rdir, dst))
    if FLIGHT:
        segdir = os.path.join(rdir, "pi_segments")
        os.makedirs(segdir, exist_ok=True)
        for name in os.listdir(tmp):
            if os.path.isdir(os.path.join(tmp, name)):
                if os.path.isdir(os.path.join(segdir, name)):
                    shutil.rmtree(os.path.join(segdir, name))
                os.replace(os.path.join(tmp, name), os.path.join(segdir, name))
        meta["launcher_tail"] = (L.read(os.path.join(rdir, "launcher.out")) or "").splitlines()[-3:]
    else:
        meta["publisher_tail"] = (L.read(os.path.join(rdir, "publisher.out")) or "").splitlines()[-1:]
    shutil.rmtree(tmp, ignore_errors=True)

def collect(meta):
    """Wait for the Pi to be reachable and the publisher (or flight launcher) to finish, then copy
    its logs. For a flight, also split the data into one run folder per segment."""
    pid = meta.get("launcher_pid" if FLIGHT else "publisher_pid")
    proc_name = "flight_launcher" if FLIGHT else "publish_multi_sensor"
    for attempt in range(1, a.retries + 1):
        if pi("true", timeout=20, connect_timeout=5).returncode != 0:
            print(f"  collect: Pi not reachable (attempt {attempt}/{a.retries}); retry in {a.retry_wait:.0f} s")
            time.sleep(0 if a.dry_run else a.retry_wait)
            continue
        if pid and pi(f"kill -0 {pid} 2>/dev/null && ps -o cmd= -p {pid} | grep -q {proc_name}").returncode == 0 \
                and not a.dry_run:
            print(f"  collect: {proc_name} (pid {pid}) still running; retry in {a.retry_wait:.0f} s")
            time.sleep(a.retry_wait)
            continue
        if meta.get("side_pid"):
            pi(f"kill -TERM -- -{meta['side_pid']} 2>/dev/null; true")      # usually stopped itself
        if not a.dry_run:
            time.sleep(1)
        tmp = os.path.join(rdir, "pi_remote")
        r = scp(f"{L.PI}:{remote}", tmp, recursive=True)
        if r.returncode != 0:
            print(f"  collect: scp failed ({r.stderr.strip()[:120]}); retry in {a.retry_wait:.0f} s")
            time.sleep(0 if a.dry_run else a.retry_wait)
            continue
        if not a.dry_run:
            arrange(tmp, meta)
        pi_status("after")
        meta.update(power_after=power(), collected=True, collected_unix=time.time(), collect_attempts=attempt)
        write_meta(meta)
        if FLIGHT and not a.dry_run:
            import flight_lib as F
            made = F.split(rdir, meta)
            meta["segments_split"] = made
            write_meta(meta)
            print(f"  split into {len(made)} segment folders")
        print(f"  collected after {attempt} attempt(s): {rdir}")
        return True
    meta.update(collected=False, collect_attempts=a.retries)
    write_meta(meta)
    print(f"  NOT collected. Later: python code/run_field.py --session {a.session} --label {a.label} --collect-only")
    return False

if a.collect_only:
    meta = json.load(open(meta_path))
    sys.exit(0 if collect(meta) else 1)

# ---------------------------------------------------------------- run
if os.path.exists(meta_path) and not a.overwrite:
    sys.exit(f"{rdir} already has a run (use another --label, or --overwrite)")
if not a.dry_run:
    os.makedirs(rdir, exist_ok=True)
what = (f"flight, schedule '{a.schedule}' at points {a.points}" if FLIGHT
        else f"QoS {a.qos}, {a.duration} s")
print(f"{'DRY RUN: ' if a.dry_run else ''}{a.session}/{a.label}: {what}, nodelay {a.nodelay}, "
      f"sidelog {a.sidelog} (stadump {a.stadump}), ping {a.ping}, pcap {a.pcap} -> {rdir}")

if pi("true", timeout=20).returncode != 0:
    sys.exit("Cannot reach the Pi over SSH (find it: getent hosts FahadsPi.local).")

print(f"  power gate: vcgencmd get_throttled, {L.POWER_GATE_N} readings over {2.5 * (L.POWER_GATE_N - 1):.0f} s ...")
pok, pw_gate = L.power_gate(pi(L.POWER_GATE_CMD, timeout=30).stdout)
print(f"  power: throttled {pw_gate['throttled']} ({', '.join(pw_gate.get('bits') or []) or 'no bits'}) -> {pw_gate['reason']}")
if not pok:
    sys.exit(f"Refusing to start: Pi power supply not good enough ({pw_gate['reason']}).\n"
             "  Under-voltage slows the Pi's CPU and may affect the radio; data from such a run are confounded.\n"
             "  Fix the supply first (check the voltage at the Pi's 5 V pins with the drone powered, under load).\n"
             "  Bit 0x10000 stays set until the Pi reboots: after fixing the supply, reboot the Pi (ask first),\n"
             "  wait for chrony to settle, then run again.")

print(f"  chrony gate: {L.GATE_N} readings over {5 * (L.GATE_N - 1)} s ...")
gate_out = pi(L.GATE_CMD, timeout=150).stdout
ok, ch = L.chrony_gate(L.split_gate_output(gate_out), stall_s=a.stall_lastrx, fresh_s=a.fresh_lastrx,
                       max_offset_ms=a.max_offset_ms)
print(f"  chrony: LastRx {ch['lastrx_s']} s, offset {[None if x is None else round(x, 3) for x in ch['offset_ms']]} ms,"
      f" update interval {ch['update_interval_s']} s, new samples {ch.get('new_samples')} -> {ch['reason']}")
if not ok:
    sys.exit(f"Refusing to start: chrony unhealthy ({ch['reason']}).\n"
             f"  Restart it (needs sudo):  {L.CHRONY_RESTART}\n"
             f"  then wait ~1 min and check:  ssh {L.PI} 'chronyc -n sources; chronyc tracking'")

pw = "<password>" if a.dry_run else (os.environ.get("MQTT_PASSWORD") or getpass.getpass("MQTT password: "))
mq = L.run(["mosquitto", "-h"])
mq_text = (mq.stdout or mq.stderr).strip()
meta = {
    "session": a.session, "label": a.label, "run_id": a.label, "mode": "flight" if FLIGHT else "field",
    "notes": a.notes, "distance_m": None if FLIGHT else a.distance_m, "pi_height_m": a.pi_height_m,
    "router_height_m": a.router_height_m,
    "qos": None if FLIGHT else a.qos, "duration_s": None if FLIGHT else a.duration,
    "imu_hz": a.imu_hz, "bmp_hz": 2.0, "ina_hz": 2.0, "nodelay": a.nodelay,
    "sidelog": a.sidelog, "stadump_s": a.stadump if a.sidelog else None, "ping_hz": a.ping, "pcap": a.pcap,
    "git_commit": L.run(["git", "-C", L.HOME, "rev-parse", "HEAD"]).stdout.strip(),
    "git_dirty": bool(L.run(["git", "-C", L.HOME, "status", "--porcelain", "code"]).stdout.strip()),
    "paho_laptop": importlib.metadata.version("paho-mqtt"),
    "mosquitto": mq_text.splitlines()[0] if mq_text else "unknown",
    "pi_kernel": pi("uname -r").stdout.strip(),
    "pi_publisher_sha1": pi(f"sha1sum {L.PI_DIR}/publish_multi_sensor.py").stdout.split()[:1],
    "laptop_publisher_sha1": L.run(["sha1sum", os.path.join(L.HOME, "code/pi/publish_multi_sensor.py")]).stdout.split()[:1],
    "power_gate": pw_gate, "chrony_check": ch, "remote_dir": remote,
}
if meta["pi_publisher_sha1"] != meta["laptop_publisher_sha1"] and not a.dry_run:
    print("  WARNING: the Pi's publish_multi_sensor.py differs from code/pi/ (copy it with scp first?)")

pi_status("before")
meta["power_before"] = power()
pi(f"rm -rf {remote} && mkdir -p {remote}")

# laptop logger first, so it is subscribed before the first message
cap = pings = None
if a.pcap:
    cap = local(["dumpcap", "-q", "-i", "enp0s31f6", "-f", L.PCAP_FILTER, "-i", "lo", "-f", L.PCAP_FILTER,
                 "-w", os.path.join(rdir, "capture.pcapng")],
                stdout=subprocess.DEVNULL, stderr=open(os.path.join(rdir, "dumpcap.err"), "w") if not a.dry_run else None)
    if not a.dry_run:
        time.sleep(2)
        if cap.poll() is not None:
            sys.exit(f"dumpcap exited early; see {rdir}/dumpcap.err")
lg = local([sys.executable, "-u", os.path.join(L.HOME, "code", "logger.py"),
            "--out", os.path.join(rdir, "rx_all.csv" if FLIGHT else "rx.csv"),
            "--qos", "2", "--nodelay", str(a.nodelay)],
           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=dict(os.environ, MQTT_PASSWORD=pw))
if lg is not None:
    line = lg.stdout.readline()
    if "Subscribed" not in line:
        lg.kill()
        sys.exit(f"Logger did not start: {line.strip()}")

# side logging, detached, stops itself after the run
if a.sidelog:
    if scp(os.path.join(L.HOME, "code", "pi", "side_log.sh"), f"{L.PI}:{L.PI_DIR}/side_log.sh").returncode != 0:
        sys.exit("Could not copy side_log.sh to the Pi.")
    meta["side_log_sha1"] = L.run(["sha1sum", os.path.join(L.HOME, "code", "pi", "side_log.sh")]).stdout.split()[0]
    if FLIGHT:   # schedule built now, so its times start after the loggers are up
        sched = F.build(a.schedule, points, distances, time.time() + 5, a.start_delay_s, a.gap_s, a.move_s,
                        a.imu_hz, a.nodelay)
        max_s = sched["end_unix"] - time.time() + a.tail_s + 60
    else:
        max_s = a.duration + a.tail_s + 30
    out = pi(f"setsid nohup bash {L.PI_DIR}/side_log.sh {remote}/side {a.stadump} {max_s:.0f} "
             f"> /dev/null 2>&1 < /dev/null & echo $!").stdout.strip()
    if not out.isdigit():
        sys.exit(f"side_log.sh did not start: {out!r}")
    meta["side_pid"] = int(out)
if a.ping:
    iv = f"{1 / a.ping:.3f}"
    pings = [local(["ping", "-D", "-O", "-i", iv, host],
                   stdout=open(os.path.join(rdir, f"ping_{tag}.txt"), "w") if not a.dry_run else None,
                   stderr=subprocess.STDOUT)
             for tag, host in [("pi", L.PI.split("@")[1]), ("router", L.ROUTER)]]
if not a.dry_run:
    time.sleep(1)

# publisher (or flight launcher), detached with a fixed end; the password goes over stdin, never
# on a command line. Only the setsid command goes to the background (braces): `read` must run in
# the foreground, because a background job's stdin is /dev/null, and $! must be the child's PID.
if FLIGHT and not a.sidelog:
    sched = F.build(a.schedule, points, distances, time.time() + 5, a.start_delay_s, a.gap_s, a.move_s,
                    a.imu_hz, a.nodelay)
t_start = time.time()
if FLIGHT:
    if not a.dry_run:
        L.save(os.path.join(rdir, "schedule.json"), json.dumps(sched, indent=2))
    for src_, dst_ in [(os.path.join(rdir, "schedule.json"), f"{L.PI}:{remote}/schedule.json"),
                       (os.path.join(L.HOME, "code", "pi", "flight_launcher.py"), f"{L.PI}:{L.PI_DIR}/flight_launcher.py")]:
        if scp(src_, dst_).returncode != 0:
            sys.exit(f"Could not copy {src_} to the Pi.")
    meta["schedule"] = sched
    meta["launcher_sha1"] = L.run(["sha1sum", os.path.join(L.HOME, "code", "pi", "flight_launcher.py")]).stdout.split()[:1]
    child_cmd = (f"python flight_launcher.py --schedule $HOME/{remote}/schedule.json --outdir $HOME/{remote} "
                 f"> $HOME/{remote}/launcher.out 2>&1 < /dev/null")
else:
    child_cmd = (f"python publish_multi_sensor.py --duration {a.duration} --qos {a.qos} "
                 f"--imu-hz {a.imu_hz} --nodelay {a.nodelay} --log $HOME/{remote}/pi_log.csv "
                 f"> $HOME/{remote}/publisher.out 2>&1 < /dev/null")
cmd = (f"cd {L.PI_DIR} && source .venv/bin/activate && read -r MQTT_PASSWORD && export MQTT_PASSWORD && "
       f"{{ setsid nohup {child_cmd} & echo $!; }}")
out = pi(cmd, stdin=pw + "\n", timeout=60).stdout.strip()
if not out.isdigit():
    print(f"{'Launcher' if FLIGHT else 'Publisher'} did not start: {out!r}")
    if lg is not None:
        lg.send_signal(signal.SIGINT)
    sys.exit(1)
meta.update({"launcher_pid" if FLIGHT else "publisher_pid": int(out), "start_unix": t_start, "collected": False})
write_meta(meta)
if FLIGHT:
    tt = F.timetable(sched)
    if not a.dry_run:
        L.save(os.path.join(rdir, "timetable.txt"), tt + "\n")
    print("\n" + tt + "\n")
    end = sched["end_unix"] + a.tail_s
    print(f"  launcher started (pid {out}); laptop logger runs until {F.hms(end)}. "
          f"Keep this window open; Ctrl-C stops only the laptop logger.")
else:
    end = t_start + a.duration + a.tail_s
    print(f"  publisher started (pid {out}) at {time.strftime('%H:%M:%S')}; "
          f"logging until +{a.duration + a.tail_s:.0f} s")

# laptop side: wait for the window, without touching the Pi
try:
    while not a.dry_run and time.time() < end:
        time.sleep(min(10, max(0.1, end - time.time())))
except KeyboardInterrupt:
    print("  interrupted: stopping the laptop logger; the Pi side runs to its fixed end")
for proc in (pings or []) + [lg, cap]:
    if proc is not None:
        proc.send_signal(signal.SIGINT if proc is lg else signal.SIGTERM)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
meta["laptop_stop_unix"] = time.time()
write_meta(meta)

if FLIGHT and not a.dry_run:
    print("  land, then the logs are collected (retries while the Pi is out of reach)")
collect(meta)
if not a.dry_run:
    try:
        import pandas as pd
        rx = pd.read_csv(os.path.join(rdir, "rx_all.csv" if FLIGHT else "rx.csv"))
        print(f"  rx: {len(rx)} messages, p50 {rx.latency_ms.median():.2f} ms, p95 {rx.latency_ms.quantile(.95):.2f} ms"
              f" | {meta.get('publisher_tail')}")
    except Exception as e:
        print(f"  could not read rx.csv ({e})")
