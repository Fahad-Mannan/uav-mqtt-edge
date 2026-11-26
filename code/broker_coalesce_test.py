#!/usr/bin/env python3
"""Laptop-only test: does the broker hold a PUBREC when the PUBLISH arrives in the
same TCP segment right after a PUBREL?

A raw-socket MQTT 3.1.1 client (TCP_NODELAY, so each send() is one segment) runs these
conditions in random order each round. Message a is a QoS 2 PUBLISH already answered by
PUBREC; message b is a new QoS 2 PUBLISH.
  lone        PUBLISH a on its own after a quiet gap (its PUBREC delay is the sample)
  combined    one send(): PUBREL a + PUBLISH b    (the pattern seen in pcap_q2)
  reversed    one send(): PUBLISH b + PUBREL a
  back2back   send(PUBREL a); send(PUBLISH b) immediately
  separate    send(PUBREL a); 2 ms pause; send(PUBLISH b)
For b it measures the time from the send to its PUBREC. If no PUBREC arrives within
--hold-ms, it sends a PINGREQ and checks whether the PUBREC follows right after it
(that is, whether new incoming data releases the held packet).

By default it starts a private broker (the same mosquitto binary, as this user, on
127.0.0.1:1884, anonymous, temporary config) and a paho QoS 2 subscriber, like the
logger. --broker-host/--port/--user test an existing broker (password from
MQTT_PASSWORD or a prompt).
"""
import argparse, getpass, os, random, select, shutil, socket, struct, subprocess
import sys, tempfile, time
import pandas as pd
import paho.mqtt.client as mqtt

p = argparse.ArgumentParser()
p.add_argument("--rounds", type=int, default=50)
p.add_argument("--hold-ms", type=float, default=200.0)
p.add_argument("--broker-host", default=None, help="existing broker; default: start a private one")
p.add_argument("--port", type=int, default=1884)
p.add_argument("--user", default=None)
p.add_argument("--no-subscriber", action="store_true")
p.add_argument("--broker-nodelay", action="store_true",
               help="private broker only: add 'set_tcp_nodelay true' to its config")
p.add_argument("--out", default=None, help="CSV of every trial")
a = p.parse_args()

ns = time.perf_counter_ns


# ------------------------------------------------------------------ MQTT encoding
def varint(n):
    out = bytearray()
    while True:
        b, n = n % 128, n // 128
        out.append(b | (128 if n else 0))
        if not n:
            return bytes(out)


def s16(b):
    return struct.pack("!H", len(b)) + b


def connect_pkt(cid, user, pw):
    flags = 0x02 | (0x80 if user else 0) | (0x40 if pw else 0)
    body = s16(b"MQTT") + bytes([4, flags]) + struct.pack("!H", 60) + s16(cid.encode())
    if user:
        body += s16(user.encode())
    if pw:
        body += s16(pw.encode())
    return b"\x10" + varint(len(body)) + body


def publish_pkt(pid, topic=b"test/coalesce/ina219"):
    payload = (b'{"uav_id": "uav_01", "sensor": "ina219", "seq": %d, "data": '
               b'{"bus_voltage_v": 0.9, "current_ma": 0.1, "power_mw": 0.0}}' % pid)
    body = s16(topic) + struct.pack("!H", pid) + payload
    return b"\x34" + varint(len(body)) + body


pubrel_pkt = lambda pid: b"\x62\x02" + struct.pack("!H", pid)
PINGREQ = b"\xc0\x00"
NAMES = {2: "CONNACK", 5: "PUBREC", 7: "PUBCOMP", 13: "PINGRESP"}


class Client:
    def __init__(self, host, port, user, pw):
        self.s = socket.create_connection((host, port), timeout=5)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.s.setblocking(False)
        self.buf = b""
        self.s.sendall(connect_pkt(f"coalesce-{os.getpid()}", user, pw))
        got = self.wait(lambda t, k, pid: k == "CONNACK", 5000)
        if not got or got[3][1] != 0:
            raise SystemExit("broker refused the test connection")

    def send(self, data):
        self.s.setblocking(True)
        self.s.sendall(data)
        self.s.setblocking(False)
        return ns()

    def wait(self, match, timeout_ms):
        """Read packets until match(t, kind, pid) is true; return (t, kind, pid, body)."""
        end = ns() + int(timeout_ms * 1e6)
        while True:
            while len(self.buf) >= 2:
                i, rl, mul = 1, 0, 1
                while i < len(self.buf):
                    rl += (self.buf[i] & 127) * mul
                    mul *= 128
                    i += 1
                    if not self.buf[i - 1] & 128:
                        break
                else:
                    break
                if len(self.buf) < i + rl:
                    break
                kind = NAMES.get(self.buf[0] >> 4, str(self.buf[0] >> 4))
                body = self.buf[i:i + rl]
                self.buf = self.buf[i + rl:]
                pid = struct.unpack("!H", body[:2])[0] if kind in ("PUBREC", "PUBCOMP") else None
                if match(self.t_read, kind, pid):
                    return self.t_read, kind, pid, body
            left = (end - ns()) / 1e9
            if left <= 0:
                return None
            if select.select([self.s], [], [], left)[0]:
                chunk = self.s.recv(65536)
                self.t_read = ns()
                if not chunk:
                    raise SystemExit("broker closed the connection")
                self.buf += chunk


# ------------------------------------------------------------------ setup
broker = tmp = None
pw = None
host = a.broker_host or "127.0.0.1"
if a.broker_host is None:
    exe = shutil.which("mosquitto") or "/usr/sbin/mosquitto"
    tmp = tempfile.mkdtemp(prefix="coalesce_")
    conf = os.path.join(tmp, "mosquitto.conf")
    with open(conf, "w") as fh:
        fh.write(f"listener {a.port} 127.0.0.1\nallow_anonymous true\npersistence false\n"
                 f"log_dest file {tmp}/mosquitto.log\n"
                 + ("set_tcp_nodelay true\n" if a.broker_nodelay else ""))
    broker = subprocess.Popen([exe, "-c", conf], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection((host, a.port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        broker.kill()
        raise SystemExit("private broker did not start")
    version = subprocess.run([exe, "-h"], capture_output=True, text=True).stdout.splitlines()[0]
else:
    pw = os.environ.get("MQTT_PASSWORD") or getpass.getpass("MQTT password: ")
    version = "existing broker"
print(f"Broker: {host}:{a.port} ({version}); subscriber: {not a.no_subscriber}; "
      f"broker set_tcp_nodelay: {a.broker_nodelay if broker else 'unknown'}")

sub = None
if not a.no_subscriber:
    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if a.user:
        sub.username_pw_set(a.user, pw)
    sub.connect(host, a.port, 60)
    sub.loop_start()
    sub.subscribe("test/coalesce/#", qos=2)
    time.sleep(0.5)

c = Client(host, a.port, a.user, pw)
pid_counter = [0]


def next_pid():
    pid_counter[0] = pid_counter[0] % 65535 + 1
    return pid_counter[0]


def finish(pid):
    """Complete message pid (PUBREL -> PUBCOMP) so nothing stays in flight."""
    c.send(pubrel_pkt(pid))
    if not c.wait(lambda t, k, x: k == "PUBCOMP" and x == pid, 2000):
        raise SystemExit(f"no PUBCOMP for {pid}")


# ------------------------------------------------------------------ trials
rows = []
conds = ["combined", "reversed", "back2back", "separate"]
try:
    for rnd in range(a.rounds):
        for cond in random.sample(conds, len(conds)):
            time.sleep(0.02)
            pa, pb = next_pid(), next_pid()
            t_send = c.send(publish_pkt(pa))            # message a, alone
            got = c.wait(lambda t, k, x: k == "PUBREC" and x == pa, 2000)
            rows.append({"round": rnd, "cond": "lone", "pubrec_ms": (got[0] - t_send) / 1e6,
                         "held": None, "released_by_ping": None})
            time.sleep(0.005)
            if cond == "combined":
                t_send = c.send(pubrel_pkt(pa) + publish_pkt(pb))
            elif cond == "reversed":
                t_send = c.send(publish_pkt(pb) + pubrel_pkt(pa))
            elif cond == "back2back":
                c.send(pubrel_pkt(pa))
                t_send = c.send(publish_pkt(pb))
            else:
                c.send(pubrel_pkt(pa))
                time.sleep(0.002)
                t_send = c.send(publish_pkt(pb))
            got = c.wait(lambda t, k, x: k == "PUBREC" and x == pb, a.hold_ms)
            row = {"round": rnd, "cond": cond, "held": got is None, "released_by_ping": None}
            if got is None:                             # held: does new data release it?
                t_ping = c.send(PINGREQ)
                got = c.wait(lambda t, k, x: k == "PUBREC" and x == pb, 2000)
                row["released_by_ping"] = got is not None and (got[0] - t_ping) / 1e6 < 5
                row["after_ping_ms"] = (got[0] - t_ping) / 1e6 if got else None
            row["pubrec_ms"] = (got[0] - t_send) / 1e6 if got else None
            rows.append(row)
            finish(pb)                                  # PUBCOMP for a is read and dropped

            c.wait(lambda t, k, x: False, 5)
finally:
    try:
        c.send(b"\xe0\x00")
    except OSError:
        pass
    if sub:
        sub.loop_stop()
        sub.disconnect()
    if broker:
        broker.terminate()
        broker.wait(5)
        shutil.rmtree(tmp, ignore_errors=True)

df = pd.DataFrame(rows)
if a.out:
    df.to_csv(a.out, index=False)
print(f"\n{a.rounds} rounds. PUBREC delay for the new message (ms):")
order = ["lone", "combined", "reversed", "back2back", "separate"]
summ = df.groupby("cond")["pubrec_ms"].describe(percentiles=[.5, .95, .99])
summ["held_>%gms" % a.hold_ms] = df.groupby("cond")["held"].apply(
    lambda s: f"{int(s.sum())}/{len(s)}" if s.notna().any() else "-")
summ["released_by_ping"] = df.groupby("cond")["released_by_ping"].apply(
    lambda s: f"{int(s.dropna().sum())}/{s.notna().sum()}" if s.notna().any() else "-")
print(summ.loc[order, ["count", "50%", "95%", "99%", "max", summ.columns[-2], summ.columns[-1]]]
      .round(3).to_string())
