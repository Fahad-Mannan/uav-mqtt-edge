#!/usr/bin/env python3
"""Run a measurement campaign.

For every condition: start the logger on this laptop, start the publisher on the Pi
over SSH, then collect the Pi's local log, clock and Wi-Fi status into one folder.
"""
import argparse, getpass, glob, importlib.metadata, json, os, shutil, signal, subprocess, sys, time
import pandas as pd

PI = "fahadspi@192.168.1.3"
PI_DIR = "mqtt_uav_test"
HOME = os.path.expanduser("~/uav-mqtt")

p = argparse.ArgumentParser()
p.add_argument("--name", required=True, help="campaign name, e.g. pilot1")
p.add_argument("--qos", default="0,1,2", help="comma-separated QoS levels")
p.add_argument("--repeats", type=int, default=2)
p.add_argument("--duration", type=int, default=30, help="seconds per run")
p.add_argument("--imu-hz", type=float, default=20.0)
p.add_argument("--nodelay", default="1",
               help="0, 1 or 0,1 (1 = set TCP_NODELAY on Pi publisher and logger; default 1 since q0_nd_ab); "
                    "a list is interleaved like QoS and adds _nd<N> to the run name")
p.add_argument("--sidelog", type=int, default=1, choices=[0, 1],
               help="1 = run code/pi/side_log.sh on the Pi during each run")
p.add_argument("--stadump", type=float, default=1.0,
               help="station dump interval for --sidelog, s (0 = off)")
p.add_argument("--ping", default="0",
               help="ping rate in Hz from this laptop to the Pi and the router during each run (0 = off); "
                    "a list (e.g. 0,50) is interleaved and adds _pg<Hz> to the run name")
p.add_argument("--pcap", default="0",
               help="1 = dumpcap on enp0s31f6 + lo per run (CONNECT segments filtered out); "
                    "0,1 is interleaved and adds _pc<N> to the run name")
p.add_argument("--counterbalance", default="auto", choices=["auto", "0", "1"],
               help="reverse the condition order in every second repeat (ABBA); auto = on when "
                    "--nodelay, --pcap or --ping has more than one level")
p.add_argument("--plan-only", action="store_true",
               help="print the run order and names, then exit (no password, no SSH)")
a = p.parse_args()
nodelays = [int(x) for x in a.nodelay.split(",")]
assert all(n in (0, 1) for n in nodelays), "--nodelay takes 0, 1 or 0,1"
pcaps = [int(x) for x in a.pcap.split(",")]
assert all(x in (0, 1) for x in pcaps), "--pcap takes 0, 1 or 0,1"
pings_hz = [float(x) for x in a.ping.split(",")]
assert all(x >= 0 for x in pings_hz), "--ping takes rates >= 0"
qos_list = [int(x) for x in a.qos.split(",")]
multi = len(nodelays) > 1 or len(pcaps) > 1 or len(pings_hz) > 1
cb = multi if a.counterbalance == "auto" else a.counterbalance == "1"
conds = [(q, n, pc, pg) for q in qos_list for n in nodelays for pc in pcaps for pg in pings_hz]
order = [c + (r,) for r in range(1, a.repeats + 1) for c in (conds[::-1] if cb and r % 2 == 0 else conds)]

def run_name(q, nd, pc, pg, r):
    return (f"qos{q}" + (f"_nd{nd}" if len(nodelays) > 1 else "") + (f"_pc{pc}" if len(pcaps) > 1 else "")
            + (f"_pg{pg:g}" if len(pings_hz) > 1 else "") + f"_rep{r}")

if a.plan_only:
    print(f"{len(order)} runs x {a.duration} s (+ ~15-20 s overhead each), counterbalance {'on' if cb else 'off'}:")
    for i, (q, nd, pc, pg, r) in enumerate(order, 1):
        print(f"  {i:3d} {run_name(q, nd, pc, pg, r):<28} qos {q} nodelay {nd} pcap {pc} ping {pg:g} Hz")
    sys.exit(0)

ROUTER = "192.168.1.1"
PI_IP = PI.split("@")[1]
# Drops CONNECT (packet type 0x10), which carries the password; keeps pure ACKs
PCAP_FILTER = ("tcp port 1883 and ((ip[2:2] - ((ip[0]&0xf)<<2) - ((tcp[12]&0xf0)>>2)) = 0 "
               "or tcp[((tcp[12]&0xf0)>>2):1] != 0x10)")

pw = os.environ.get("MQTT_PASSWORD") or getpass.getpass("MQTT password: ")
base = os.path.join(HOME, "data", a.name)
os.makedirs(base, exist_ok=True)

def run(cmd, stdin=None, timeout=None):
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout)

def pi(cmd, stdin=None, timeout=None):
    return run(["ssh", "-o", "BatchMode=yes", PI, cmd], stdin, timeout)

def save(path, text):
    with open(path, "w") as fh:
        fh.write(text)

if pi("true").returncode != 0:
    sys.exit("Cannot reach the Pi over SSH (check the network and ssh-copy-id).")
mq = run(["mosquitto", "-h"])
mq_text = (mq.stdout or mq.stderr).strip()
meta_common = {
    "campaign": a.name,
    "git_commit": run(["git", "-C", HOME, "rev-parse", "HEAD"]).stdout.strip(),
    "paho_laptop": importlib.metadata.version("paho-mqtt"),
    "mosquitto": mq_text.splitlines()[0] if mq_text else "unknown",
    "pi_kernel": pi("uname -r").stdout.strip(),
}

if a.sidelog:
    src = os.path.join(HOME, "code", "pi", "side_log.sh")
    if run(["scp", "-q", src, f"{PI}:{PI_DIR}/side_log.sh"]).returncode != 0:
        sys.exit("Could not copy side_log.sh to the Pi.")
    meta_common["side_log_sha1"] = run(["sha1sum", src]).stdout.split()[0]

def pi_status(rdir, tag):
    save(os.path.join(rdir, f"chrony_{tag}.txt"), pi("chronyc tracking").stdout)
    save(os.path.join(rdir, f"wifi_{tag}.txt"), pi("/usr/sbin/iw dev wlan0 link").stdout)
    save(os.path.join(rdir, f"station_{tag}.txt"),
         pi("/usr/sbin/iw dev wlan0 get power_save; /usr/sbin/iw dev wlan0 station dump").stdout)

def read(path):
    try:
        return open(path).read().strip()
    except OSError:
        return None

def power_state():
    """CPU governor/frequency on both machines, and the laptop's power source."""
    cpus = sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq"))
    ps = {os.path.basename(p): read(f"{p}/online")
          for p in glob.glob("/sys/class/power_supply/*") if read(f"{p}/type") in ("Mains", "USB")}
    prof = run(["powerprofilesctl", "get"]) if shutil.which("powerprofilesctl") else None
    lap = {"governor": sorted({read(f"{c}/scaling_governor") for c in cpus}),
           "driver": read(f"{cpus[0]}/scaling_driver") if cpus else None,
           "epp": sorted({read(f"{c}/energy_performance_preference") for c in cpus} - {None}),
           "cur_khz": [int(read(f"{c}/scaling_cur_freq") or 0) for c in cpus],
           "power_supply_online": ps,
           "power_profile": prof.stdout.strip() if prof else None}
    out = pi("cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort -u | tr '\\n' ' '; echo; "
             "cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq | tr '\\n' ' '; echo; "
             "vcgencmd measure_clock arm; vcgencmd get_throttled").stdout.splitlines()
    pis = {"raw": out}
    if len(out) >= 4:
        pis = {"governor": out[0].split(), "cur_khz": [int(x) for x in out[1].split()],
               "arm_hz": int(out[2].split("=")[1]), "throttled": out[3].split("=")[1]}
    return {"laptop": lap, "pi": pis}

def stop(proc, sig=signal.SIGINT, timeout=10):
    if proc is None:
        return
    proc.send_signal(sig)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()

print(f"{len(order)} runs x {a.duration} s -> {base} (counterbalance {'on' if cb else 'off'})")

for q, nd, pc, pg, r in order:
    run_id = run_name(q, nd, pc, pg, r)
    rdir = os.path.join(base, run_id)
    os.makedirs(rdir, exist_ok=True)
    rx = os.path.join(rdir, "rx.csv")
    cap = pings = None
    if pc:
        cap = subprocess.Popen(
            ["dumpcap", "-q", "-i", "enp0s31f6", "-f", PCAP_FILTER, "-i", "lo", "-f", PCAP_FILTER,
             "-w", os.path.join(rdir, "capture.pcapng")],
            stdout=subprocess.DEVNULL, stderr=open(os.path.join(rdir, "dumpcap.err"), "w"))
        time.sleep(2)                    # capture must be running before the publisher connects
        if cap.poll() is not None:
            sys.exit(f"dumpcap exited early; see {rdir}/dumpcap.err")
    lg = subprocess.Popen(
        [sys.executable, "-u", os.path.join(HOME, "code", "logger.py"),
         "--out", rx, "--qos", "2", "--nodelay", str(nd)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env=dict(os.environ, MQTT_PASSWORD=pw))
    line = lg.stdout.readline()
    if "Subscribed" not in line:
        lg.kill()
        sys.exit(f"Logger did not start: {line.strip()}")
    pi_status(rdir, "before")
    power_before = power_state()
    side_pid, side_dir = None, f"{PI_DIR}/side_{a.name}_{run_id}"
    if a.sidelog:
        out = pi(f"rm -rf {side_dir}; setsid nohup bash {PI_DIR}/side_log.sh {side_dir} {a.stadump} "
                 f"> /dev/null 2>&1 < /dev/null & echo $!").stdout.strip()
        side_pid = int(out) if out.isdigit() else None
        if side_pid is None:
            sys.exit(f"side_log.sh did not start: {out!r}")
    if pg:
        iv = f"{1 / pg:.3f}"
        pings = [subprocess.Popen(["ping", "-D", "-O", "-i", iv, host],
                                  stdout=open(os.path.join(rdir, f"ping_{tag}.txt"), "w"),
                                  stderr=subprocess.STDOUT)
                 for tag, host in [("pi", PI_IP), ("router", ROUTER)]]
    time.sleep(1)                        # side loggers and pings running before the first sample
    t_start = time.time()
    remote = (f"cd {PI_DIR} && source .venv/bin/activate && read -r MQTT_PASSWORD && "
              f"export MQTT_PASSWORD && python publish_multi_sensor.py "
              f"--duration {a.duration} --qos {q} --imu-hz {a.imu_hz} --nodelay {nd} "
              f"--log pi_log_{a.name}_{run_id}.csv")
    res = pi(remote, stdin=pw + "\n", timeout=a.duration + 90)
    time.sleep(2)
    for pg in pings or []:
        stop(pg)
    if side_pid:
        pi(f"kill -TERM -- -{side_pid}")
        time.sleep(1)
        run(["scp", "-q", "-r", f"{PI}:{side_dir}", os.path.join(rdir, "pi_side")])
    pi_status(rdir, "after")
    power_after = power_state()
    lg.send_signal(signal.SIGINT)
    try:
        lg.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        lg.kill()
    stop(cap, signal.SIGTERM)
    run(["scp", "-q", f"{PI}:{PI_DIR}/pi_log_{a.name}_{run_id}.csv",
         os.path.join(rdir, "pi_log.csv")])
    tail = res.stdout.strip().splitlines()[-1:]
    meta = dict(meta_common, run_id=run_id, qos=q, repeat=r, duration_s=a.duration,
                imu_hz=a.imu_hz, nodelay=nd, start_unix=t_start, publisher_rc=res.returncode,
                sidelog=a.sidelog, stadump_s=a.stadump if a.sidelog else None,
                ping_hz=pg, pcap=pc, counterbalance=cb, power_before=power_before, power_after=power_after,
                publisher_tail=tail, publisher_err=res.stderr.strip()[-300:])
    save(os.path.join(rdir, "meta.json"), json.dumps(meta, indent=2))
    try:
        df = pd.read_csv(rx)
        print(f"{run_id}: {len(df)} msgs, mean {df['latency_ms'].mean():.2f} ms, "
              f"p95 {df['latency_ms'].quantile(0.95):.2f} ms | {tail}")
    except Exception as e:
        print(f"{run_id}: could not read results ({e})")
    time.sleep(3)
