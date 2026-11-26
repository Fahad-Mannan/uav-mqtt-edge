#!/usr/bin/env python3
"""Bench link-outage run over the real Pi - router - laptop path (docs/bench_outage_2026-11-24.md).

One run per call: run_field.py in flight mode with ONE segment (qos<Q>:<pre+outage+post>) starts the
Pi publisher at a planned wall-clock time; this script cuts the laptop's wired link to the router at
segment start + --pre-s for --outage-s, then restores it. The Pi stays associated to the router; only
IP traffic between the laptop and the router/Pi is cut (an outage of the laptop's link, not a Wi-Fi
fade).

The cut, on enp0s31f6 only (hard-coded; wlp4s0 and the default route are never touched):
  - egress:  tc qdisc add dev enp0s31f6 root netem loss 100%     (laptop -> Pi: PUBACK, TCP ACK, ...)
  - ingress: tc qdisc add dev enp0s31f6 handle ffff: ingress
             tc filter add dev enp0s31f6 parent ffff: protocol all prio 1 matchall action drop
                                                                   (Pi -> laptop: PUBLISH, ...)
  An egress qdisc alone only drops what the laptop sends: the Pi's PUBLISHes would still reach the
  broker, so the ingress drop is needed for a two-way outage.
Safety, in this order:
  1. before the cut, a detached root timer (systemd-run --on-active=<outage + 30 s>) that deletes
     both qdiscs, so the link comes back even if this script is killed (SIGKILL, laptop sleep, ...);
     the cut is not applied unless the timer was created;
  2. the normal removal at the planned end, in a finally block, also on Ctrl-C / SIGTERM / SIGHUP;
  3. after removal: stop the timer, check that no netem/ingress qdisc is left, ping the Pi.
sudo: every privileged call is `sudo -n` (never prompts). Run `sudo -v` in the same terminal first
(Ubuntu caches it per terminal for 15 min; every sudo call in a run refreshes it). If the cache has
expired, the script refuses before starting anything. The laptop logger connects to 192.168.1.4,
the laptop's own address, so its traffic goes over lo and is not cut.

Modes:
  --selftest N   cut for N s with no MQTT run: ping the Pi during (must fail) and after (must work)
  (default)      one outage run; writes <run>/outage.json, then runs analysis/outage_report.py
  --dry-run      prints every command (run_field.py --dry-run, tc, systemd-run), no sudo, no cut
  --cleanup      removes any leftover qdisc and guard timer (sudo -n), then shows the state
Usage:
  python code/bench_outage.py --session bench_outage_2026-11-24 --label A_q1_o30 --qos 1 --outage-s 30 \
      --notes "..." [--pre-s 30 --post-s 90] [--dry-run]
"""
import argparse, json, os, re, shutil, signal, subprocess, sys, threading, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DEV = "enp0s31f6"                    # the ONLY interface this script ever touches
LAPTOP_IP, PI_IP = "192.168.1.4", "192.168.1.3"
TC, SYSTEMD_RUN, SYSTEMCTL = "/usr/sbin/tc", "/usr/bin/systemd-run", "/usr/bin/systemctl"
GUARD_MARGIN_S = 30

CUT = [[TC, "qdisc", "add", "dev", DEV, "root", "netem", "loss", "100%"],
       [TC, "qdisc", "add", "dev", DEV, "handle", "ffff:", "ingress"],
       [TC, "filter", "add", "dev", DEV, "parent", "ffff:", "protocol", "all", "prio", "1", "matchall",
        "action", "drop"]]
UNCUT = [[TC, "qdisc", "del", "dev", DEV, "root"], [TC, "qdisc", "del", "dev", DEV, "ingress"]]
UNCUT_SH = f"{TC} qdisc del dev {DEV} root; {TC} qdisc del dev {DEV} ingress; true"


def log(msg):
    print(f"[outage {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(cmd, check=False):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(cmd)} -> rc {r.returncode}: {r.stderr.strip()}")
    return r


def qdisc_state():
    out = sh([TC, "qdisc", "show", "dev", DEV]).stdout
    return out, ("netem" in out) or ("ingress" in out)


def ping(n=1, w=1):
    r = sh(["ping", "-c", str(n), "-W", str(w), "-I", DEV, PI_IP])
    return r.returncode == 0


def preflight(dry):
    probs = []
    addr = sh(["ip", "-4", "-br", "addr", "show", "dev", DEV]).stdout
    if LAPTOP_IP not in addr or " UP " not in f" {addr} ":
        probs.append(f"{DEV} is not UP with {LAPTOP_IP}: {addr.strip()!r}")
    dr = sh(["ip", "route", "show", "default"]).stdout
    if f"dev {DEV}" in dr:
        probs.append(f"the default route uses {DEV} ({dr.strip()}); refusing")
    out, cut = qdisc_state()
    if cut:
        probs.append(f"{DEV} already has a netem/ingress qdisc (run --cleanup): {out.strip()}")
    units = sh([SYSTEMCTL, "list-units", "--all", "--no-legend", "uav-outage-guard*"]).stdout.strip()
    if units:
        probs.append(f"leftover guard units (run --cleanup): {units}")
    if not dry and sh(["sudo", "-n", "true"]).returncode:
        probs.append("sudo credentials not cached: run `sudo -v` in this terminal first")
    return probs


class Outage:
    """Cut and restore, with the guard timer. remove() is idempotent."""

    def __init__(self, unit, outage_s, dry):
        self.unit, self.outage_s, self.dry = unit, outage_s, dry
        self.applied = self.guard = False
        self.ev = {"unit": unit, "guard_after_s": outage_s + GUARD_MARGIN_S}

    def _sudo(self, cmd, check=True):
        if self.dry:
            print("  [dry-run sudo -n] " + " ".join(cmd))
            return None
        return sh(["sudo", "-n"] + cmd, check=check)

    def apply(self):
        guard = [SYSTEMD_RUN, f"--unit={self.unit}", f"--on-active={self.outage_s + GUARD_MARGIN_S}s",
                 "--timer-property=AccuracySec=1s", "/bin/sh", "-c", UNCUT_SH]
        self.ev["t_guard_request"] = time.time()
        self._sudo(guard)
        self.guard = True
        self.ev["t_guard_created"] = time.time()
        try:
            self.ev["t_cut_request"] = time.time()
            for c in CUT:
                self._sudo(c)
                self.applied = True
            self.ev["t_on"] = time.time()            # outage start = all three commands done
        except Exception as e:
            self.ev["apply_error"] = str(e)
            log(f"cut failed, removing: {e}")
            self.remove()
            raise
        if not self.dry:
            self.ev["qdisc_during"] = qdisc_state()[0]

    def remove(self):
        if not (self.applied or self.guard):
            return
        if self.applied:
            self.ev["t_uncut_request"] = time.time()
            rs = [self._sudo(c, check=False) for c in UNCUT]
            self.ev["t_off"] = time.time()
            # judged by the resulting state, not by tc's messages (deleting an absent qdisc fails harmlessly)
            if not self.dry and qdisc_state()[1]:
                self.ev["remove_errors"] = [r.stderr.strip() for r in rs if r is not None and r.returncode]
                log("REMOVE FAILED, qdisc still present; the guard timer deletes it within "
                    f"{GUARD_MARGIN_S} s of the planned end. Or run: python code/bench_outage.py --cleanup. "
                    + "; ".join(self.ev["remove_errors"]))
                return                       # keep the guard timer armed
            self.applied = False
        if self.guard:
            self._sudo([SYSTEMCTL, "stop", f"{self.unit}.timer"], check=False)
            self._sudo([SYSTEMCTL, "reset-failed", f"{self.unit}.service", f"{self.unit}.timer"], check=False)
            self.guard = False
        if not self.dry:
            out, cut = qdisc_state()
            self.ev["qdisc_after"] = out
            self.ev["clean_after"] = not cut
            log(f"link restored: qdisc clean={not cut}")


def install_signal_handlers():
    def h(sig, frame):
        raise KeyboardInterrupt(f"signal {sig}")
    for s in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, h)


def selftest(a):
    o = Outage(f"uav-outage-guard-selftest-{int(time.time())}", a.selftest, a.dry_run)
    log(f"self-test: ping before: {'ok' if a.dry_run or ping(3) else 'FAILED'}")
    try:
        o.apply()
        log(f"cut applied ({a.selftest} s)")
        if not a.dry_run:
            time.sleep(1)
            p = ping(2)
            log(f"ping during the cut: {'REPLIED (cut NOT working)' if p else 'no reply (cut works)'}")
            o.ev["ping_during_ok"] = p
            time.sleep(max(0, a.selftest - 3))
    finally:
        o.remove()
    if not a.dry_run:
        time.sleep(1)
        p = ping(3)
        o.ev["ping_after_ok"] = p
        log(f"ping after: {'ok' if p else 'FAILED'}")
        ok = (not o.ev["ping_during_ok"]) and p and o.ev.get("clean_after")
        log("SELF-TEST " + ("PASSED" if ok else "FAILED"))
        print(json.dumps(o.ev, indent=1))
        return 0 if ok else 1
    return 0


def cleanup(a):
    for c in UNCUT:
        r = sh(["sudo", "-n"] + c)
        print(" ".join(c), "->", r.returncode, r.stderr.strip())
    units = sh([SYSTEMCTL, "list-units", "--all", "--no-legend", "--plain", "uav-outage-guard*"]).stdout.split()
    for u in [x for x in units if x.startswith("uav-outage-guard")]:
        print("stop", u, sh(["sudo", "-n", SYSTEMCTL, "stop", u]).returncode)
        sh(["sudo", "-n", SYSTEMCTL, "reset-failed", u])
    print(qdisc_state()[0])
    return 0


def run(a):
    rdir = os.path.join(ROOT, "data", a.session, a.label)
    seg_s = a.pre_s + a.outage_s + a.post_s
    unit = f"uav-outage-guard-{re.sub('[^A-Za-z0-9_-]', '_', a.label)}"
    conf = open("/etc/mosquitto/conf.d/lab.conf").read()
    limits = {k: (re.search(rf"^{k}\s+(\d+)", conf, re.M) or [None, "default"])[1]
              for k in ("max_queued_messages", "max_inflight_messages")}
    notes = (f"bench outage: cut {DEV} (netem loss 100% egress + ingress drop) at +{a.pre_s:g} s for "
             f"{a.outage_s:g} s, then {a.post_s:g} s clean; broker max_queued_messages {limits['max_queued_messages']}, "
             f"max_inflight_messages {limits['max_inflight_messages']}; " + a.notes)
    cmd = [sys.executable, os.path.join(ROOT, "code", "run_field.py"), "--session", a.session, "--label", a.label,
           "--schedule", f"qos{a.qos}:{seg_s:g}", "--points", "bench", "--point-distances", "1", "--distance-m", "1",
           "--start-delay-s", str(a.start_delay_s), "--gap-s", "3", "--tail-s", str(a.tail_s), "--notes", notes]
    if a.dry_run:
        cmd.append("--dry-run")
    log("run_field: " + " ".join(cmd[1:]))
    o = Outage(unit, a.outage_s, a.dry_run)
    if a.dry_run:
        log(f"[dry-run] segment qos{a.qos} {seg_s:g} s; at segment start + {a.pre_s:g} s:")
        o.apply()
        log(f"[dry-run] {a.outage_s:g} s later:")
        o.remove()
        return subprocess.call(cmd)
    t_script = time.time()
    rf = subprocess.Popen(cmd)
    result = {"label": a.label, "qos": a.qos, "pre_s": a.pre_s, "outage_s": a.outage_s, "post_s": a.post_s,
              "segment_s": seg_s, "dev": DEV, "cut": [" ".join(c) for c in CUT], "broker_limits": limits,
              "events": o.ev}
    sched_path = os.path.join(rdir, "schedule.json")
    try:
        # wait for this run's schedule.json (written after both gates pass)
        while not (os.path.exists(sched_path) and os.path.getmtime(sched_path) >= t_script):
            if rf.poll() is not None:
                log(f"run_field.py exited (rc {rf.returncode}) before the schedule existed: no outage applied")
                return rf.returncode or 1
            time.sleep(0.2)
        seg = json.load(open(sched_path))["segments"][0]
        t_cut = seg["start_unix"] + a.pre_s
        result.update(segment_start_planned=seg["start_unix"], t_on_planned=t_cut, t_off_planned=t_cut + a.outage_s)
        log(f"segment starts {time.strftime('%H:%M:%S', time.localtime(seg['start_unix']))}; "
            f"cut planned {time.strftime('%H:%M:%S', time.localtime(t_cut))} for {a.outage_s:g} s")
        while time.time() < t_cut - 0.3:
            if rf.poll() is not None:
                log(f"run_field.py exited (rc {rf.returncode}) before the planned cut: no outage applied")
                return rf.returncode or 1
            time.sleep(0.1)
        while time.time() < t_cut:
            pass
        o.apply()
        log(f"CUT ON ({DEV}); restores at {time.strftime('%H:%M:%S', time.localtime(o.ev['t_on'] + a.outage_s))}")
        t_end = o.ev["t_on"] + a.outage_s
        # one ping 2 s in: confirms the cut (expect no reply)
        while time.time() < o.ev["t_on"] + 2:
            time.sleep(0.05)
        o.ev["ping_during_ok"] = ping(1, 1)
        while time.time() < t_end - 0.3:
            time.sleep(0.1)
        while time.time() < t_end:
            pass
    finally:
        o.remove()
        if "t_off" in o.ev:
            log(f"CUT OFF; outage {o.ev['t_off'] - o.ev['t_on']:.2f} s")
            time.sleep(1)
            o.ev["ping_after_ok"] = ping(3)
            log(f"ping after: {'ok' if o.ev['ping_after_ok'] else 'FAILED'}")
        if os.path.isdir(rdir):
            json.dump(result, open(os.path.join(rdir, "outage.json"), "w"), indent=1)
    rc = rf.wait()
    log(f"run_field.py finished, rc {rc}")
    if rc == 0 and os.path.exists(os.path.join(rdir, "outage.json")):
        subprocess.call([sys.executable, os.path.join(ROOT, "analysis", "outage_report.py"), rdir])
    return rc


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--session")
    p.add_argument("--label")
    p.add_argument("--qos", type=int, choices=[0, 1, 2])
    p.add_argument("--outage-s", type=float)
    p.add_argument("--pre-s", type=float, default=30)
    p.add_argument("--post-s", type=float, default=90)
    p.add_argument("--start-delay-s", type=int, default=10)
    p.add_argument("--tail-s", type=int, default=45)
    p.add_argument("--notes", default="")
    p.add_argument("--selftest", type=float, default=None, help="cut for N s without an MQTT run")
    p.add_argument("--cleanup", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if a.cleanup:
        return cleanup(a)
    probs = preflight(a.dry_run)
    if probs:
        for x in probs:
            log("REFUSED: " + x)
        return 2
    install_signal_handlers()
    if a.selftest:
        if not 3 <= a.selftest <= 30:
            sys.exit("--selftest: 3-30 s")
        return selftest(a)
    if None in (a.session, a.label, a.qos, a.outage_s):
        sys.exit("--session, --label, --qos and --outage-s are required")
    if not 5 <= a.outage_s <= 300:
        sys.exit("--outage-s: 5-300 s")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
