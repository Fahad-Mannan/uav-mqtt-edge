#!/usr/bin/env python3
"""Can MQTT 5 let the publisher detect QoS 2 messages that Mosquitto's default in-flight limit rejects?

Laptop only. Starts a private Mosquitto (2.0.18) on a free 127.0.0.1 port with a temporary config
and Mosquitto's default limits (no max_inflight_messages / max_queued_messages lines), anonymous,
debug logging to a file; never touches the system broker on 1883.

Each run: one QoS 2 subscriber (MQTT 3.1.1, the same in every variant, --sub-delay-ms per message),
then one publisher sends --n (50) QoS 2 messages at once with no client-side in-flight limit
(max_inflight_messages_set(0), like paho's backlog resend after a reconnect). With the default
max_inflight_messages 20, which in Mosquitto 2.0.18 also limits *incoming* unreleased QoS 2, the
broker accepts the first 20 and answers the rest with PUBREC reason 0x97 (quota exceeded).
Variants (publisher protocol):
  v311     MQTTv311: a 3.1.1 PUBREC has no reason code field
  v5       MQTTv5
  v5_rm    (extra) MQTTv5 with the client's in-flight limit = the Receive Maximum the broker sent in
           CONNACK, i.e. what a client that honours Receive Maximum would do
Per message: publish rc, the reason code passed to on_publish (and is_failure), is_published(),
wait_for_publish(), and whether the subscriber got it. On the wire: dumpcap on lo (no sudo: the
binary has cap_net_raw and the user is in group wireshark), PUBREC / PUBCOMP reason codes from the
broker to the publisher; also the broker's debug log ("Sending PUBREC ... rc").

  python tests/test_mqtt5_quota.py --python /path/to/python-with-paho-2.1 [--reps 3] [--out data/mqtt5_check]
Writes <out>/messages.csv, summary.csv, summary.md, and per run the capture and broker log.
"""
import argparse, json, os, re, shutil, signal, socket, subprocess, sys, tempfile, time
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from pcap_qos2_handshake import read_pcapng, parse_tcp, Stream  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--python", default=sys.executable, help="interpreter with the paho version to test (2.1.0)")
ap.add_argument("--reps", type=int, default=3)
ap.add_argument("--n", type=int, default=50)
ap.add_argument("--sub-delay-ms", type=float, default=2.0)
ap.add_argument("--variants", default="v311,v5,v5_rm")
ap.add_argument("--out", default=os.path.join(ROOT, "data", "mqtt5_check"))
a = ap.parse_args()

CHILD = r'''
import json, sys, time, threading
import paho.mqtt as pm, paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
port, variant, n, sub_delay = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), float(sys.argv[4]) / 1e3
topic = f"quota/{variant}/{time.time_ns()}"
got = {}
def on_msg(c, u, m):
    time.sleep(sub_delay)
    got[json.loads(m.payload)["i"]] = time.time()
sub = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"sub-{variant}", protocol=mqtt.MQTTv311)
sub.on_message = on_msg
sub.connect("127.0.0.1", port); sub.loop_start()
ok = threading.Event()
sub.on_subscribe = lambda *x: ok.set()
sub.subscribe(topic, qos=2); ok.wait(5)

proto = mqtt.MQTTv311 if variant == "v311" else mqtt.MQTTv5
pub = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"pub-{variant}", protocol=proto)
cb, conn = {}, {}
connected = threading.Event()
def on_connect(c, u, flags, rc, props):
    conn["rc"] = str(rc)
    conn["receive_maximum"] = getattr(props, "ReceiveMaximum", None) if props is not None else None
    connected.set()
def on_publish(c, u, mid, rc, props):
    cb[mid] = {"value": getattr(rc, "value", rc), "name": str(rc), "is_failure": bool(getattr(rc, "is_failure", False))}
pub.on_connect, pub.on_publish = on_connect, on_publish
probe_rm = None
if variant == "v5_rm":
    # paho 2.1 can't change the in-flight limit on a live connection: learn Receive Maximum first
    pr, ev = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="probe", protocol=mqtt.MQTTv5), threading.Event()
    def pc(c, u, f, rc, props):
        global probe_rm
        probe_rm = getattr(props, "ReceiveMaximum", None); ev.set()
    pr.on_connect = pc; pr.connect("127.0.0.1", port); pr.loop_start(); ev.wait(5); pr.disconnect(); pr.loop_stop()
    pub.max_inflight_messages_set(probe_rm or 65535)
else:
    pub.max_inflight_messages_set(0)                       # unlimited, as paho's resend after a reconnect
pub.connect("127.0.0.1", port, clean_start=True) if proto == mqtt.MQTTv5 else pub.connect("127.0.0.1", port)
# manual network loop (no loop_start): publish() writes each PUBLISH at once, but no PUBREC is read
# (so no PUBREL sent) until loop() runs, so all n PUBLISHes reach the broker before any PUBREL, as in
# the backlog paho resends at once after a reconnect. A threaded loop interleaves PUBRELs with the
# burst and frees quota slots (trial: 24 and 37 accepted instead of 20).
t0 = time.time()
while not connected.is_set() and time.time() - t0 < 5:
    pub.loop(0.05)
conn["client_inflight_limit"] = probe_rm or 0
infos = []
for i in range(n):
    infos.append((i, pub.publish(topic, json.dumps({"i": i}), qos=2)))
t0 = time.time()
while len(cb) < n and time.time() - t0 < 10:
    pub.loop(0.05)
t0 = time.time()
while time.time() - t0 < 1.0 + n * sub_delay:               # stragglers to the subscriber
    pub.loop(0.05)
rows = []
for i, inf in infos:
    r = {"i": i, "mid": inf.mid, "publish_rc": int(inf.rc)}
    try:
        r["is_published"] = bool(inf.is_published())
    except Exception as e:
        r["is_published"] = f"raised {type(e).__name__}"
    try:
        inf.wait_for_publish(timeout=0.2)
        r["wait_for_publish"] = "returned" if inf.is_published() else "timed out"
    except Exception as e:
        r["wait_for_publish"] = f"raised {type(e).__name__}: {e}"
    c = cb.get(inf.mid)
    r.update(on_publish_called=c is not None, on_publish_rc=None if c is None else c["value"],
             on_publish_rc_name=None if c is None else c["name"],
             on_publish_is_failure=None if c is None else c["is_failure"], delivered=i in got)
    rows.append(r)
pub.disconnect(); pub.loop(0.1); sub.disconnect(); sub.loop_stop()
print(json.dumps({"paho": pm.__version__, "connack": conn, "rows": rows}))
'''


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def start_broker(d, port):
    conf, log = os.path.join(d, "mosquitto.conf"), os.path.join(d, "mosquitto.log")
    # default limits: no max_inflight_messages / max_queued_messages lines
    open(conf, "w").write(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n"
                          f"set_tcp_nodelay true\nlog_dest file {log}\nlog_type all\nlog_timestamp_format %s\n")
    exe = shutil.which("mosquitto") or "/usr/sbin/mosquitto"
    ver = subprocess.run([exe, "-h"], capture_output=True, text=True).stdout.splitlines()[0]
    p = subprocess.Popen([exe, "-c", conf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close(); return p, log, ver
        except OSError:
            time.sleep(0.1)
    p.kill(); raise SystemExit("private broker did not start")


def mqtt5_decode(pkt):
    """type, packet id and reason code of PUBLISH/PUBACK/PUBREC/PUBREL/PUBCOMP (3.1.1 or 5)."""
    ptype, i, rl, k = pkt[0] >> 4, 1, 0, 0
    while True:
        b = pkt[i]; rl += (b & 127) << (7 * k); i += 1; k += 1
        if not b & 128:
            break
    body = pkt[i:i + rl]
    e = {"type": ptype, "rl": rl}
    if ptype in (4, 5, 6, 7) and rl >= 2:
        e["pid"] = int.from_bytes(body[:2], "big")
        e["rc"] = body[2] if rl > 2 else None            # None: no reason code field (3.1.1, or 5 with rc 0)
    elif ptype == 3 and (pkt[0] >> 1) & 3:
        tl = int.from_bytes(body[:2], "big")
        e["pid"] = int.from_bytes(body[2 + tl:4 + tl], "big")
    elif ptype == 2:
        e["rc"] = body[1] if rl >= 2 else None             # CONNACK return / reason code
    return e


def wire(pcap, broker_port, pub_cid):
    """Per publisher packet id: PUBREC and PUBCOMP reason codes sent by the broker, PUBREL sent or not."""
    streams, pubport = {}, None
    for iface, ts, d in read_pcapng(pcap):
        t = parse_tcp(iface["linktype"], d)
        if not t or not t[7]:
            continue
        src, sp, dst, dp, seq, ack, fl, pay = t
        key = (sp, dp)
        for pkt, _ in streams.setdefault(key, Stream()).feed(seq, pay):
            e = mqtt5_decode(pkt)
            if e["type"] == 1 and dp == broker_port and pub_cid.encode() in pkt:
                pubport = sp                                # this connection is the publisher's
            e["dir"] = "to_broker" if dp == broker_port else "from_broker"
            e["cport"] = sp if dp == broker_port else dp
            streams.setdefault("events", []).append(e)
    out = {}
    for e in streams.get("events", []):
        if e["cport"] != pubport or "pid" not in e:
            continue
        r = out.setdefault(e["pid"], {"wire_pubrec_rc": "none", "wire_pubrel_sent": False, "wire_pubcomp_rc": "none"})
        if e["type"] == 5 and e["dir"] == "from_broker":
            r["wire_pubrec_rc"] = "no field (0)" if e["rc"] is None else f"0x{e['rc']:02x}"
        elif e["type"] == 6 and e["dir"] == "to_broker":
            r["wire_pubrel_sent"] = True
        elif e["type"] == 7 and e["dir"] == "from_broker":
            r["wire_pubcomp_rc"] = "no field (0)" if e["rc"] is None else f"0x{e['rc']:02x}"
    return out


def broker_log(log, pub_cid):
    """Per packet id: PUBREC / PUBCOMP rc as Mosquitto logs it for the publisher."""
    out = {}
    for line in open(log, errors="replace"):
        m = re.search(r"Sending (PUBREC|PUBCOMP) to (\S+) \(m(\d+), rc(\d+)\)", line)
        if m and m.group(2) == pub_cid:
            out.setdefault(int(m.group(3)), {})[f"log_{m.group(1).lower()}_rc"] = f"0x{int(m.group(4)):02x}"
    return out


def run_one(variant, rep, outdir):
    d = os.path.join(outdir, f"{variant}_rep{rep}"); os.makedirs(d, exist_ok=True)
    port = free_port()
    broker, log, ver = start_broker(d, port)
    pcap = os.path.join(d, "capture.pcapng")
    cap = subprocess.Popen(["dumpcap", "-q", "-i", "lo", "-f", f"tcp port {port}", "-w", pcap],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(50):                                   # dumpcap writes the header when it is up
            if os.path.exists(pcap) and os.path.getsize(pcap) > 0:
                break
            time.sleep(0.1)
        time.sleep(0.5)
        r = subprocess.run([a.python, "-c", CHILD, str(port), variant, str(a.n), str(a.sub_delay_ms)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise SystemExit(f"{variant} rep{rep}: client failed:\n{r.stderr}")
        res = json.loads(r.stdout.strip().splitlines()[-1])
        time.sleep(0.5)
    finally:
        cap.send_signal(signal.SIGINT); cap.wait(10)
        broker.terminate(); broker.wait(10)
    W, L = wire(pcap, port, f"pub-{variant}"), broker_log(log, f"pub-{variant}")
    rows = []
    for x in res["rows"]:
        rows.append({"variant": variant, "rep": rep, **x, **W.get(x["mid"], {}), **L.get(x["mid"], {})})
    meta = {"variant": variant, "rep": rep, "port": port, "paho": res["paho"], "broker": ver, "connack": res["connack"]}
    json.dump(meta, open(os.path.join(d, "meta.json"), "w"), indent=1)
    return rows, meta


def summarise(M, metas):
    S = []
    for (v, rep), g in M.groupby(["variant", "rep"], sort=False):
        rej = g.log_pubrec_rc == "0x97"
        believed = g.on_publish_called & ~g.on_publish_is_failure.fillna(False).astype(bool)
        S.append({"variant": v, "rep": rep, "paho": metas[(v, rep)]["paho"],
                  "connack_receive_maximum": metas[(v, rep)]["connack"].get("receive_maximum"),
                  "sent": len(g),
                  "pubrec_rc0_log": int((g.log_pubrec_rc == "0x00").sum()), "pubrec_0x97_log": int(rej.sum()),
                  "pubrec_0x97_wire": int((g.wire_pubrec_rc == "0x97").sum()),
                  "pubrec_wire_no_rc_field": int((g.wire_pubrec_rc == "no field (0)").sum()),
                  "pubrel_after_0x97": int((rej & g.wire_pubrel_sent).sum()),
                  "pubcomp_rc_after_0x97": ",".join(sorted(set(g[rej].wire_pubcomp_rc)))
                  if rej.any() else "",
                  "is_published_true": int((g.is_published == True).sum()),  # noqa: E712
                  "on_publish_success": int(believed.sum()),
                  "believed_delivered": int((believed & (g.is_published == True)).sum()),  # noqa: E712
                  "delivered": int(g.delivered.sum()),
                  "rejected_flagged_by_on_publish": int((rej & g.on_publish_is_failure.fillna(False).astype(bool)).sum()),
                  "on_publish_rc_for_rejected": ",".join(sorted(set(g[rej].on_publish_rc_name.astype(str)))) if rej.any() else ""})
    return pd.DataFrame(S)


def main():
    os.makedirs(a.out, exist_ok=True)
    rows, metas = [], {}
    for rep in range(1, a.reps + 1):                          # variants interleaved within each repeat
        for v in a.variants.split(","):
            r, meta = run_one(v, rep, a.out)
            rows += r; metas[(v, rep)] = meta
            print(f"{v} rep{rep}: done (paho {meta['paho']}, {meta['broker']}, CONNACK {meta['connack']})")
    M = pd.DataFrame(rows)
    M.to_csv(os.path.join(a.out, "messages.csv"), index=False)
    S = summarise(M, metas)
    S.to_csv(os.path.join(a.out, "summary.csv"), index=False)
    md = ["| " + " | ".join(S.columns) + " |", "|" + "---|" * len(S.columns)] + \
         ["| " + " | ".join(str(x) for x in r) + " |" for r in S.itertuples(index=False)]
    open(os.path.join(a.out, "summary.md"), "w").write(
        f"# MQTT 5 vs 3.1.1: detecting incoming-QoS-2 quota rejections\n\n{a.n} QoS 2 messages at once, private "
        f"Mosquitto with default limits, subscriber delay {a.sub_delay_ms:g} ms.\n\n" + "\n".join(md) + "\n")
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(S.to_string(index=False))
    # per-message pattern of the first repeat of each variant
    for v, g in M[M.rep == 1].groupby("variant", sort=False):
        k = g.groupby(["log_pubrec_rc", "wire_pubrec_rc", "wire_pubrel_sent", "wire_pubcomp_rc", "on_publish_rc_name",
                       "is_published", "delivered"], dropna=False).i.agg(["count", "min", "max"]).reset_index()
        print(f"\n{v} rep1 (messages i = min..max):\n{k.to_string(index=False)}")


if __name__ == "__main__":
    main()
