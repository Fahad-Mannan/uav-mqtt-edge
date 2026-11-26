"""Helpers shared by the measurement runners (run_field.py; run_campaign.py has its own copies):
SSH, power state, Pi power gate (get_throttled), chrony health."""
import glob, os, re, shutil, subprocess

PI = "fahadspi@192.168.1.3"
PI_DIR = "mqtt_uav_test"
HOME = os.path.expanduser("~/uav-mqtt")
BROKER_IP = "192.168.1.4"
ROUTER = "192.168.1.1"
CHRONY_RESTART = f"ssh -t {PI} 'sudo systemctl restart chrony'"
# Drops CONNECT (packet type 0x10), which carries the password; keeps pure ACKs
PCAP_FILTER = ("tcp port 1883 and ((ip[2:2] - ((ip[0]&0xf)<<2) - ((tcp[12]&0xf0)>>2)) = 0 "
               "or tcp[((tcp[12]&0xf0)>>2):1] != 0x10)")


def run(cmd, stdin=None, timeout=None):
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout)


def pi(cmd, stdin=None, timeout=None, connect_timeout=10):
    return run(["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout}", PI, cmd],
               stdin, timeout)


def save(path, text):
    with open(path, "w") as fh:
        fh.write(text)


def read(path):
    try:
        return open(path).read().strip()
    except OSError:
        return None


def laptop_power():
    cpus = sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq"))
    ps = {os.path.basename(p): read(f"{p}/online")
          for p in glob.glob("/sys/class/power_supply/*") if read(f"{p}/type") in ("Mains", "USB")}
    bat = {os.path.basename(p): {"capacity": read(f"{p}/capacity"), "status": read(f"{p}/status")}
           for p in glob.glob("/sys/class/power_supply/*") if read(f"{p}/type") == "Battery"}
    prof = run(["powerprofilesctl", "get"]) if shutil.which("powerprofilesctl") else None
    return {"governor": sorted({read(f"{c}/scaling_governor") for c in cpus}),
            "driver": read(f"{cpus[0]}/scaling_driver") if cpus else None,
            "epp": sorted({read(f"{c}/energy_performance_preference") for c in cpus} - {None}),
            "cur_khz": [int(read(f"{c}/scaling_cur_freq") or 0) for c in cpus],
            "power_supply_online": ps, "battery": bat,
            "power_profile": prof.stdout.strip() if prof else None}


PI_POWER_CMD = ("cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort -u | tr '\\n' ' '; echo; "
                "cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq | tr '\\n' ' '; echo; "
                "vcgencmd measure_clock arm; vcgencmd get_throttled")


# ---------------------------------------------------------------- power gate
# vcgencmd get_throttled bits: 0x1 under-voltage now, 0x2 freq capped now, 0x4 throttled now,
# 0x8 soft temp limit now; 0x10000/0x20000/0x40000/0x80000 = the same "has occurred since boot".
# 2026-11-22: the Pi on the drone's 3S + LM2596 supply read 0x50005 in every ref1 sample and in
# 8-52% of f1b samples. The sticky bit 0x10000 only clears on reboot.
UV_NOW, UV_SINCE_BOOT = 0x1, 0x10000
POWER_GATE_N = 5
POWER_GATE_CMD = (f"for i in $(seq 1 {POWER_GATE_N}); do vcgencmd get_throttled; echo '=== THROTTLED'; "
                  f"[ $i -lt {POWER_GATE_N} ] && sleep 2.5; done")    # 5 readings over 10 s
_THROTTLE_BITS = {0x1: "under-voltage now", 0x2: "ARM frequency capped now", 0x4: "throttled now",
                  0x8: "soft temperature limit now", 0x10000: "under-voltage since boot",
                  0x20000: "frequency capped since boot", 0x40000: "throttled since boot",
                  0x80000: "soft temperature limit since boot"}


def throttle_bits(value):
    return [name for bit, name in _THROTTLE_BITS.items() if value & bit]


def power_gate(text):
    """Output of POWER_GATE_CMD -> (ok, details). Refuses if any reading has 0x1 (under-voltage
    now) or 0x10000 (under-voltage since boot), or if no reading parses."""
    vals = [int(m.group(1), 16) for m in re.finditer(r"throttled=(0x[0-9a-fA-F]+)", text)]
    d = {"n": len(vals), "throttled": [hex(v) for v in vals]}
    reasons = []
    if not vals:
        reasons.append("no get_throttled reading")
    else:
        now = sum(bool(v & UV_NOW) for v in vals)
        if now:
            reasons.append(f"under-voltage NOW (bit 0x1) in {now} of {len(vals)} readings")
        if any(v & UV_SINCE_BOOT for v in vals):
            reasons.append("under-voltage has occurred since boot (bit 0x10000; clears only on reboot)")
        union = 0
        for v in vals:
            union |= v
        d["bits"] = throttle_bits(union)                     # every bit seen in any reading
    d["reason"] = "; ".join(reasons) or "ok"
    return not reasons, d


def parse_pi_power(text):
    out = text.splitlines()
    if len(out) < 4:
        return {"raw": out}
    try:
        return {"governor": out[0].split(), "cur_khz": [int(x) for x in out[1].split()],
                "arm_hz": int(out[2].split("=")[1]), "throttled": out[3].split("=")[1]}
    except (IndexError, ValueError):
        return {"raw": out}


# ---------------------------------------------------------------- chrony health
_UNIT = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400, "y": 31536000}


def parse_lastrx(tok):
    """chronyc LastRx column: seconds, or with m/h/d/y suffix; '-' = never."""
    m = re.fullmatch(r"(\d+)([smhdy]?)", tok)
    return int(m.group(1)) * _UNIT[m.group(2)] if m else float("inf")


# LastRx is the time since chronyd last ACCEPTED a sample. Over Wi-Fi it routinely reaches 15-30 s
# while the Pi polls every 4 s and gets every reply (2026-11-21: chronyd used ~1 sample in 5-8).
# A real stall (2026-11-20, after a reconnect) grew without bound (38 -> 160 s). So:
STALL_LASTRX_S = 60.0     # above this: stalled
FRESH_LASTRX_S = 10.0     # the start gate needs at least one reading at or below this
MAX_OFFSET_MS = 1.0
# A stall can also show as LastRx rising steadily from a low value with the last sample frozen
# (2026-11-22: 1, 6, ..., 31 s passed the old 7-reading gate, then grew to 118 s). So the gate also
# needs a sample accepted DURING the readings: LastRx drops, or the "Last sample" value changes.
# 60 s of readings, so a slow but healthy update interval (~20 s over Wi-Fi) still shows one.
GATE_N = 13
GATE_CMD = (f"for i in $(seq 1 {GATE_N}); do chronyc -n sources; chronyc tracking; echo '=== READING'; "
            f"[ $i -lt {GATE_N} ] && sleep 5; done")          # 13 readings over 60 s, one SSH call


def chrony_reading(sources_text, tracking_text, server=BROKER_IP):
    """One reading -> dict (state, reach, lastrx_s, offset_ms, ...) or {'error': ...}."""
    d = {"server": server}
    line = next((l for l in sources_text.splitlines() if re.search(rf"\s{re.escape(server)}\s", f" {l} ")), None)
    if line is None:
        return dict(d, error=f"{server} not in chronyc sources")
    f = line.split()
    d.update(state=f[0], stratum=f[2], poll=f[3], reach=f[4], lastrx_s=parse_lastrx(f[5]),
             # offset part only: the "+/- error" grows with time since the sample even without a new one
             last_sample=" ".join(f[6:]).split("+/-")[0].strip())
    m = re.search(r"System time\s*:\s*([\d.]+) seconds (slow|fast)", tracking_text)
    if not m:
        return dict(d, error="no System time in chronyc tracking")
    d["offset_ms"] = float(m.group(1)) * 1e3 * (1 if m.group(2) == "fast" else -1)
    m = re.search(r"Last offset\s*:\s*([-+\d.]+)", tracking_text)
    d["last_offset_ms"] = float(m.group(1)) * 1e3 if m else None
    m = re.search(r"Update interval\s*:\s*([\d.]+)", tracking_text)
    d["update_interval_s"] = float(m.group(1)) if m else None
    return d


def split_gate_output(text):
    """Output of GATE_CMD -> list of readings (each: sources + tracking text together)."""
    return [chunk for chunk in text.split("=== READING") if "System time" in chunk or "192.168" in chunk]


def chrony_gate(readings, server=BROKER_IP, stall_s=STALL_LASTRX_S, fresh_s=FRESH_LASTRX_S,
                max_offset_ms=MAX_OFFSET_MS):
    """Start gate over several readings (each a text holding `chronyc -n sources` and `chronyc
    tracking`). OK if, in every reading, the server is selected, reach > 0, LastRx <= stall_s and
    |offset| <= max_offset_ms; at least one reading has LastRx <= fresh_s; and chronyd accepted a
    new sample during the readings (LastRx drops, or the "Last sample" value changes, between two
    consecutive readings). Returns (ok, details)."""
    rs = [chrony_reading(t, t, server) for t in readings]
    d = {"server": server, "n": len(rs), "stall_s": stall_s, "fresh_s": fresh_s, "max_offset_ms": max_offset_ms,
         "lastrx_s": [r.get("lastrx_s") for r in rs], "offset_ms": [r.get("offset_ms") for r in rs],
         "update_interval_s": [r.get("update_interval_s") for r in rs]}
    reasons = []
    if not rs:
        reasons.append("no readings")
    for r in rs:
        if "error" in r:
            reasons.append(r["error"])
    good = [r for r in rs if "error" not in r]
    if good:
        bad_state = sorted({r["state"] for r in good if not r["state"].endswith("*")})
        if bad_state:
            reasons.append(f"{server} not the selected source in some readings (state {', '.join(bad_state)})")
        if any(r["reach"] == "0" for r in good):
            reasons.append("reach 0")
        worst = max(r["lastrx_s"] for r in good)
        if worst > stall_s:
            reasons.append(f"LastRx up to {worst} s > {stall_s:.0f} s (stalled)")
        if min(r["lastrx_s"] for r in good) > fresh_s:
            reasons.append(f"no reading with LastRx <= {fresh_s:.0f} s (lowest {min(r['lastrx_s'] for r in good)} s)")
        new = sum(b["lastrx_s"] < a["lastrx_s"] or b["last_sample"] != a["last_sample"]
                  for a, b in zip(good, good[1:]))
        d["new_samples"] = new
        if not new:
            reasons.append(f"no new sample accepted during the {len(good)} readings (LastRx "
                           f"{good[0]['lastrx_s']} -> {good[-1]['lastrx_s']} s, last sample "
                           f"'{good[-1]['last_sample']}' unchanged): stalled")
        off = max(abs(r["offset_ms"]) for r in good)
        if off > max_offset_ms:
            reasons.append(f"|offset| up to {off:.3f} ms > {max_offset_ms} ms")
    d["reason"] = "; ".join(dict.fromkeys(reasons)) or "ok"
    return not reasons, d
