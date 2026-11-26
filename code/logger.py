#!/usr/bin/env python3
"""Subscribe to uav/# and log one CSV row per message, with receive time and latency."""
import argparse, csv, getpass, json, os, socket, time
import paho.mqtt.client as mqtt

p = argparse.ArgumentParser()
p.add_argument("--broker", default="192.168.1.4")
p.add_argument("--port", type=int, default=1883)
p.add_argument("--user", default="uavpi")
p.add_argument("--topic", default="uav/#")
p.add_argument("--qos", type=int, default=1)
p.add_argument("--out", default=None)
p.add_argument("--nodelay", type=int, default=0, choices=[0, 1], help="1 = set TCP_NODELAY")
a = p.parse_args()

password = os.environ.get("MQTT_PASSWORD") or getpass.getpass("MQTT password: ")
out = a.out or os.path.expanduser(
    f"~/uav-mqtt/data/run_{time.strftime('%Y%m%d_%H%M%S')}.csv")
os.makedirs(os.path.dirname(out), exist_ok=True)
f = open(out, "w", newline="")
w = csv.writer(f)
w.writerow(["t_rx_ns", "topic", "qos", "dup", "seq", "t_pub_ns", "latency_ms", "bytes"])
count = 0

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print("Connect failed:", reason_code)
        return
    client.subscribe(a.topic, qos=a.qos)
    print(f"Subscribed to {a.topic} (QoS {a.qos}); logging to {out}")

def on_message(client, userdata, msg):
    global count
    t_rx = time.time_ns()
    try:
        d = json.loads(msg.payload)
        seq = d.get("seq")
        t_pub = d.get("t_pub_ns", d.get("timestamp_ns"))
    except Exception:
        seq = t_pub = None
    lat = (t_rx - t_pub) / 1e6 if t_pub is not None else ""
    w.writerow([t_rx, msg.topic, msg.qos, int(msg.dup), seq, t_pub, lat, len(msg.payload)])
    count += 1
    if count % 20 == 0:
        f.flush()

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.username_pw_set(a.user, password)
c.on_connect = on_connect
c.on_message = on_message
c.connect(a.broker, a.port, 30)
if a.nodelay:
    c.socket().setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
try:
    c.loop_forever()
except KeyboardInterrupt:
    pass
finally:
    c.disconnect()
    f.close()
    print(f"Done: {count} messages written to {out}")
