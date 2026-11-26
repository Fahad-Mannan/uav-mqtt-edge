#!/usr/bin/env python3
"""Laptop-only link-outage test of code/pi/publish_multi_sensor.py (no Pi, no lab broker).

A private Mosquitto (127.0.0.1, own config: set_tcp_nodelay true, max_queued_messages 0,
max_inflight_messages 0, i.e. the lab config planned in docs/prep_2026-11-23.md) and the real
code/logger.py (QoS 2 subscriber, connected directly). A second private broker with Mosquitto's
defaults runs the *_defq scenarios, reported as INFO only (they lose QoS 1/2 messages: see
code/broker_queue_check.py). Each publisher (--fake-sensors) connects through its own
TCP proxy that simulates the Wi-Fi link going down and up:
  - down: nothing is forwarded either way (bytes wait in the kernel buffers, like a dead path
    where TCP keeps retransmitting); new connections are refused (like "no route");
  - up: if the publisher closed its socket during the outage, whatever it wrote into it is
    discarded (never reached the broker) and the broker side is closed; otherwise forwarding
    resumes. If the broker dropped the client (keepalive 1.5 x 30 s = 45 s), the proxy closes
    the publisher side too, as an RST from the laptop would.
All scenarios run in parallel (topics separated by --uav). The full run takes ~4.5 min; --quick
runs only the short ones (~1 min).

Checks: publisher exit and duration; pi_log.csv has every sample with rc/conn; TCP_NODELAY on
every socket; reconnect <= 5 s after the link returns; QoS 0 loss accounting (rc 4 = dropped by
paho, never received; rc 0 but lost = written to the dead socket between outage start and the
DISCONNECT); QoS 1/2 every (topic, seq) received with the original t_pub_ns (same payload);
the drain; a run starting while the link is down. Also paho's own semantics for a QoS 1/2
publish made while disconnected (rc, queued, on_publish later).

Usage: python tests/test_outage.py [--quick] [--python /path/to/python-with-paho]
"""
import argparse, os, select, shutil, signal, socket, subprocess, sys, tempfile, threading, time
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PUB = os.path.join(ROOT, "code", "pi", "publish_multi_sensor.py")
LOGGER = os.path.join(ROOT, "code", "logger.py")

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--quick", action="store_true", help="only the 10 s outage, start-while-down and drain cases")
ap.add_argument("--python", default=sys.executable, help="python for the publisher (e.g. a venv with paho 2.1.0)")
ap.add_argument("--keep", action="store_true", help="keep the work directory")
a = ap.parse_args()

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name} {detail}")


# ---------------------------------------------------------------- private broker
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def start_broker(tmp, name, extra=""):
    port = free_port()
    conf = os.path.join(tmp, f"{name}.conf")
    with open(conf, "w") as fh:
        fh.write(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\nset_tcp_nodelay true\n"
                 f"log_dest file {tmp}/{name}.log\nlog_type error\nlog_type warning\nlog_type notice\n"
                 f"log_type information\n{extra}")
    exe = shutil.which("mosquitto") or "/usr/sbin/mosquitto"
    proc = subprocess.Popen([exe, "-c", conf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return proc, port
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise SystemExit(f"private broker {name} did not start")


# ---------------------------------------------------------------- link proxy
class Link:
    """TCP proxy publisher <-> broker with a link that can go down and up."""
    def __init__(self, broker_port):
        self.bport, self.port = broker_port, free_port()
        self.up, self.lock, self.pairs, self.lsock = True, threading.Lock(), [], None
        self.events = []                      # (time, text)
        self._listen()
        threading.Thread(target=self._run, daemon=True).start()

    def _listen(self):
        s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", self.port)); s.listen(8); s.setblocking(False)
        self.lsock = s

    def set_up(self, up):
        with self.lock:
            if up == self.up:
                return
            self.up = up
            self.events.append((time.time(), "up" if up else "down"))
            if not up:
                self.lsock.close(); self.lsock = None          # new connections refused
            else:
                self._listen()
                for pair in list(self.pairs):
                    self._resume(pair)

    def _close(self, pair, why):
        for s in pair:
            try: s.close()
            except OSError: pass
        if pair in self.pairs:
            self.pairs.remove(pair)
        self.events.append((time.time(), f"closed: {why}"))

    def _resume(self, pair):
        """Link back: a publisher socket closed during the outage loses what it wrote."""
        c, b = pair
        data, closed = b"", False
        c.setblocking(False)
        try:
            while True:
                chunk = c.recv(65536)
                if not chunk:
                    closed = True; break
                data += chunk
        except BlockingIOError:
            pass
        except OSError:
            closed = True
        if closed:
            self._close(pair, f"publisher closed during outage, {len(data)} B discarded")
            return
        try:
            b.setblocking(True); b.sendall(data)
        except OSError:
            self._close(pair, "broker side gone"); return

    def _run(self):
        while True:
            with self.lock:
                up, ls, pairs = self.up, self.lsock, list(self.pairs)
            if not up:
                time.sleep(0.05); continue
            rl = [s for p in pairs for s in p] + ([ls] if ls else [])
            try:
                r, _, _ = select.select(rl, [], [], 0.05)
            except (OSError, ValueError):
                continue
            with self.lock:
                if not self.up:
                    continue
                for s in r:
                    if s is self.lsock:
                        try:
                            c, _ = s.accept()
                        except OSError:
                            continue
                        try:
                            b = socket.create_connection(("127.0.0.1", self.bport))
                        except OSError:
                            c.close(); continue
                        for x in (c, b):
                            x.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                        self.pairs.append((c, b))
                        continue
                    pair = next((p for p in self.pairs if s in p), None)
                    if pair is None:
                        continue
                    other = pair[1] if s is pair[0] else pair[0]
                    try:
                        s.setblocking(False)
                        data = s.recv(65536)
                    except BlockingIOError:
                        continue
                    except OSError:
                        data = b""
                    if not data:
                        self._close(pair, "EOF from " + ("publisher" if s is pair[0] else "broker")); continue
                    try:
                        other.setblocking(True); other.sendall(data)
                    except OSError:
                        self._close(pair, "send failed")


# ---------------------------------------------------------------- paho semantics (direct)
def paho_semantics(port):
    """QoS 1/2 publish while disconnected: rc, queued?, delivered and on_publish after connect?"""
    code = r'''
import sys, time, paho.mqtt as pm, paho.mqtt.client as mqtt
print("PAHO", pm.__version__)
def pub(i):
    try:
        return i.is_published()
    except RuntimeError:
        return "raises"
port, qos = int(sys.argv[1]), int(sys.argv[2])
got, acks = [], []
sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
sub.on_message = lambda c, u, m: got.append(m.payload)
sub.on_connect = lambda c, u, f, rc, p: c.subscribe("sem/#", 2)
sub.connect("127.0.0.1", port); sub.loop_start(); time.sleep(0.5)
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.on_publish = lambda cl, u, mid, rc, p: acks.append(mid)
c.reconnect_delay_set(1, 1)
c.connect_async("127.0.0.1", port)
infos = [c.publish(f"sem/{qos}", f"m{i}", qos=qos) for i in range(3)]   # before loop_start: no socket
print("RC", [int(i.rc) for i in infos], "QUEUED", len(c._out_messages), "IS_PUBLISHED", [pub(i) for i in infos])
c.loop_start(); time.sleep(3)
print("DELIVERED", len(got), "ON_PUBLISH", len(acks), "IS_PUBLISHED", [pub(i) for i in infos])
c.disconnect(); c.loop_stop(); sub.loop_stop()
'''
    out = {}
    for qos in (0, 1, 2):
        r = subprocess.run([a.python, "-c", code, str(port), str(qos)], capture_output=True, text=True, timeout=30)
        out[qos] = r.stdout.strip().replace("\n", " | ") or r.stderr.strip()[-300:]
    return out


# ---------------------------------------------------------------- scenarios
IMU, SLOW = 20.0, 2.0
RATE = IMU + 2 * SLOW                                # 24 msg/s
SCEN = [   # name, qos, outage start, outage length (s from publisher launch), duration, drain, broker
    ("o10_q0", 0, 15, 10, 45, 30, "main"), ("o10_q1", 1, 15, 10, 45, 30, "main"), ("o10_q2", 2, 15, 10, 45, 30, "main"),
    ("startdown_q0", 0, -2, 22, 40, 30, "main"), ("startdown_q1", 1, -2, 22, 40, 30, "main"),
    ("startdown_q2", 2, -2, 22, 40, 30, "main"),
    ("drain_q1", 1, 20, 30, 30, 30, "main"),           # link back at 50 s, during the drain (40-70 s)
    ("draintimeout_q1", 1, 20, 70, 30, 8, "main"),     # link back at 90 s, after the drain gave up (~48 s)
    # Mosquitto defaults (max_inflight_messages 20, max_queued_messages 1000): informational only
    ("startdown_q2_defq", 2, -2, 22, 40, 30, "defq"),
]
if not a.quick:
    SCEN += [("o60_q0", 0, 15, 60, 100, 30, "main"), ("o60_q1", 1, 15, 60, 100, 30, "main"),
             ("o60_q2", 2, 15, 60, 100, 30, "main"),
             ("o180_q0", 0, 15, 180, 220, 30, "main"), ("o180_q1", 1, 15, 180, 220, 30, "main"),
             ("o180_q2", 2, 15, 180, 220, 30, "main"),
             ("o180_q1_defq", 1, 15, 180, 220, 30, "defq"), ("o60_q2_defq", 2, 15, 60, 100, 30, "defq")]


def main():
    tmp = tempfile.mkdtemp(prefix="outage_")
    print(f"work dir: {tmp}; publisher python: {a.python}")
    procs = []
    brokers = {}
    # main = the lab config planned for 2026-11-23 (docs/prep_2026-11-23.md)
    brokers["main"] = start_broker(tmp, "main", "max_queued_messages 0\nmax_inflight_messages 0\n")
    if any(s[6] == "defq" for s in SCEN):
        brokers["defq"] = start_broker(tmp, "defq")          # Mosquitto defaults
    for b in brokers.values():
        procs.append(b[0])
    env = dict(os.environ, MQTT_PASSWORD="x")
    try:
        sem = paho_semantics(brokers["main"][1])
        for qos, txt in sem.items():
            print(f"INFO  paho semantics QoS {qos}: {txt}")
        rc_ok = all("RC [4, 4, 4]" in sem[q] for q in (0, 1, 2))
        check("paho: publish before any connection returns rc 4 (MQTT_ERR_NO_CONN) at every QoS", rc_ok)
        check("paho: QoS 0 published while disconnected is dropped (0 delivered)", "DELIVERED 0" in sem[0])
        check("paho: QoS 1 and 2 published while disconnected are queued, delivered and acked (on_publish) "
              "after connect", all("QUEUED 3" in sem[q] and "DELIVERED 3 ON_PUBLISH 3" in sem[q] for q in (1, 2)))
        check("paho: their MessageInfo keeps rc 4, so is_published()/wait_for_publish() raise even after "
              "delivery (count on_publish instead)", all(sem[q].count("'raises', 'raises', 'raises'") == 2 for q in (1, 2)))

        loggers = {}
        for name, (bp, port) in brokers.items():
            out = os.path.join(tmp, f"rx_{name}.csv")
            lp = subprocess.Popen([sys.executable, LOGGER, "--broker", "127.0.0.1", "--port", str(port), "--qos", "2",
                                   "--nodelay", "1", "--out", out], env=env, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.STDOUT)
            loggers[name] = (lp, out)
            procs.append(lp)
        time.sleep(1.5)

        links, pubs = {}, {}
        t_launch = time.time() + 3
        timeline = []                                    # (abs time, link, up?)
        for name, qos, o_start, o_len, dur, drain, bk in SCEN:
            links[name] = Link(brokers[bk][1])
            timeline += [(t_launch + o_start, name, False), (t_launch + o_start + o_len, name, True)]
        timeline.sort()
        # links whose outage starts before launch go down now
        for t, name, up in list(timeline):
            if t <= t_launch and not up:
                links[name].set_up(False); timeline.remove((t, name, up))
        while time.time() < t_launch:
            time.sleep(0.01)
        for name, qos, o_start, o_len, dur, drain, bk in SCEN:
            d = os.path.join(tmp, name); os.makedirs(d)
            out = open(os.path.join(d, "publisher.out"), "w")
            p = subprocess.Popen([a.python, PUB, "--fake-sensors", "--broker", "127.0.0.1", "--port", str(links[name].port),
                                  "--uav", name, "--qos", str(qos), "--duration", str(dur), "--imu-hz", str(IMU),
                                  "--nodelay", "1", "--drain-s", str(drain), "--log", os.path.join(d, "pi_log.csv")],
                                 env=env, stdout=out, stderr=subprocess.STDOUT)
            pubs[name] = (p, time.time())
            procs.append(p)
        end_all = max(t_launch + max(o + l, 10 + dur + dr) for _, _, o, l, dur, dr, _ in SCEN) + 5
        print(f"running {len(SCEN)} publishers, ~{end_all - time.time():.0f} s ...", flush=True)
        exits = {}
        while time.time() < end_all or any(n not in exits for n in pubs):
            now = time.time()
            while timeline and timeline[0][0] <= now:
                _, name, up = timeline.pop(0)
                links[name].set_up(up)
            for n, (p, t0) in pubs.items():
                if n not in exits and p.poll() is not None:
                    exits[n] = (p.returncode, time.time() - t0)
            if time.time() > end_all + 120:
                break
            time.sleep(0.02)
        time.sleep(3)
        for lp, _ in loggers.values():
            lp.send_signal(signal.SIGINT)
        for lp, _ in loggers.values():
            lp.wait(timeout=10)

        print()
        for name, qos, o_start, o_len, dur, drain, bk in SCEN:
            analyse(tmp, name, qos, t_launch, o_start, o_len, dur, drain, exits.get(name), loggers[bk][1], links[name])
        dropped = [l for l in open(os.path.join(tmp, "defq.log"))] if "defq" in brokers else []
        dropped = [l.strip() for l in dropped if "dropped" in l.lower()]
        if "defq" in brokers:
            lg = open(os.path.join(tmp, "defq.log")).read()
            print(f"INFO  default broker log: {len(dropped)} 'dropped' lines (max_queued_messages 1000), "
                  f"{lg.count('Bad socket read/write')} 'Bad socket read/write' lines")
        dropped_main = [l.strip() for l in open(os.path.join(tmp, "main.log")) if "dropped" in l.lower()]
        check("main broker (max_queued_messages 0, max_inflight_messages 0): no 'dropped' lines in its log", not dropped_main,
              f"({len(dropped_main)})")
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
        if not a.keep and not fails:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"kept {tmp}")


def events(path):
    ev = []
    for line in open(path):
        parts = line.split()
        if parts and parts[0] == "FINISH":
            break                                    # our own disconnect follows
        if parts and parts[0] in ("SOCKET_OPEN", "CONNECT", "DISCONNECT", "DRAIN", "NOT"):
            t = next((float(x[2:]) for x in parts if x.startswith("t=")), None)
            ev.append((parts[0], t, line.strip()))
    return ev


def analyse(tmp, name, qos, t_launch, o_start, o_len, dur, drain, ex, rx_path, link):
    d = os.path.join(tmp, name)
    if name.endswith("_defq"):                       # Mosquitto defaults: record what happens, no checks
        pl = pd.read_csv(os.path.join(d, "pi_log.csv"))
        rx = pd.read_csv(rx_path)
        rx = rx[rx.topic.str.startswith(f"uav/{name}/")].drop_duplicates(["topic", "seq"])
        ev = events(os.path.join(d, "publisher.out"))
        dr = [e[2] for e in ev if e[0] == "DRAIN"]
        nconn = sum(e[0] == "CONNECT" for e in ev)
        print(f"INFO  {name} (Mosquitto defaults): QoS {qos}, link down {o_start:+.0f}..{o_start + o_len:.0f} s: "
              f"received {len(rx)} of {len(pl)}; {nconn} connects; {dr[0] if dr else ''}")
        return
    t_down, t_up = t_launch + o_start, t_launch + o_start + o_len
    ev = events(os.path.join(d, "publisher.out"))
    print(f"--- {name}: QoS {qos}, link down {o_start:+.0f}..{o_start + o_len:.0f} s, duration {dur} s, drain {drain} s")
    rc, wall = ex if ex else (None, None)
    limit = 10 + dur + drain + 5
    check(f"{name}: publisher exits rc 0 within {limit:.0f} s", rc == 0 and wall is not None and wall <= limit,
          f"(rc {rc}, {wall and round(wall, 1)} s)")
    pl = pd.read_csv(os.path.join(d, "pi_log.csv"))
    exp = sum(int(dur * hz - 1e-9) + 1 for hz in (SLOW, IMU, SLOW))
    check(f"{name}: pi_log.csv has every sample", len(pl) == exp, f"({len(pl)} of {exp})")
    socks = [e for e in ev if e[0] == "SOCKET_OPEN"]
    conns = [e for e in ev if e[0] == "CONNECT" and "rc=Success" in e[2]]
    discs = [e for e in ev if e[0] == "DISCONNECT"]
    check(f"{name}: TCP_NODELAY on every socket", socks and all("nodelay=1" in e[2] for e in socks),
          f"({len(socks)} sockets, {len(conns)} connects, {len(discs)} disconnects)")
    after = [e[1] for e in conns if e[1] >= t_up - 0.5]
    if discs or o_start < 0:
        rec = (after[0] - t_up) if after else None
        check(f"{name}: (re)connect <= 5 s after the link returns", rec is not None and rec <= 5,
              f"({rec and round(rec, 2)} s; disconnect detected {[round(e[1] - t_down, 1) for e in discs]} s after link down)")
    else:
        print(f"INFO  {name}: no disconnect (connection survived the outage)")
    rx = pd.read_csv(rx_path)
    rx = rx[rx.topic.str.startswith(f"uav/{name}/")]
    dups = len(rx) - len(rx.drop_duplicates(["topic", "seq"]))
    rxu = rx.drop_duplicates(["topic", "seq"])
    m = pl.merge(rxu[["topic", "seq", "t_pub_ns", "latency_ms"]], on=["topic", "seq"], how="left", suffixes=("", "_rx"))
    got = m.t_pub_ns_rx.notna()
    same = (m.t_pub_ns_rx[got] == m.t_pub_ns[got]).all()
    tp = m.t_pub_ns / 1e9
    if qos == 0:
        rc4 = m.rc == 4
        lost0 = (~got) & (m.rc == 0)
        t_disc = max([e[1] for e in discs if e[1] >= t_down - 1] or [t_up])
        in_win = tp[lost0].between(t_down - 1.0, t_disc + 0.5).all() if lost0.any() else True
        check(f"{name}: QoS 0 rc 4 messages never received", not (rc4 & got).any(), f"({int(rc4.sum())} with rc 4)")
        check(f"{name}: QoS 0 rc 0 but lost only between link down and the DISCONNECT (dead socket)", in_win,
              f"({int(lost0.sum())} lost with rc 0, {int(rc4.sum())} dropped with rc 4; received {int(got.sum())} "
              f"of {len(m)})")
        out_win = ~tp.between(t_down - 1.0, max(t_up, t_disc) + 6)
        check(f"{name}: QoS 0 everything outside the outage received", got[out_win].all(),
              f"({int((~got[out_win]).sum())} missing outside)")
    else:
        if name.startswith("draintimeout"):
            dr = [e for e in ev if e[0] == "DRAIN"]
            check(f"{name}: drain timed out and says so", dr and "TIMEOUT" in dr[0][2], f"({dr and dr[0][2]})")
            check(f"{name}: undelivered only after the link went down", (~got)[tp < t_down - 1].sum() == 0,
                  f"(received {int(got.sum())} of {len(m)})")
        else:
            check(f"{name}: QoS {qos} every (topic, seq) received", got.all(),
                  f"(received {int(got.sum())} of {len(m)}, {dups} duplicates, rc counts {m.rc.value_counts().to_dict()})")
            dr = [e for e in ev if e[0] == "DRAIN"]
            check(f"{name}: drain complete", dr and "TIMEOUT" not in dr[0][2], f"({dr and dr[0][2]})")
        check(f"{name}: resent messages carry the original t_pub_ns (same payload, same seq)", same)
        if got.any():
            print(f"INFO  {name}: latency of messages published during the outage: max "
                  f"{m.latency_ms[got & tp.between(t_down, t_up)].max():.0f} ms")
    print(f"INFO  {name}: link events {[(round(t - t_launch, 1), x) for t, x in link.events]}")


main()
print(f"\n{'ALL PASS' if not fails else f'{fails} FAIL'}")
sys.exit(1 if fails else 0)
