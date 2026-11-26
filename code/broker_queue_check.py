#!/usr/bin/env python3
"""Does the broker drop a burst of QoS 1/2 messages? (Mosquitto max_queued_messages, max_inflight_messages)

A deliberately slow subscriber (--sub-delay-ms per message) and a publisher that sends --n
messages at once with no client-side in-flight limit, like the backlog paho resends after a
reconnect, to a unique topic; once at QoS 1 and once at QoS 2. Prints how many arrived.
Mosquitto 2.0.18 defaults lose messages in both cases while the publisher gets every ack:
  - max_queued_messages 1000: QoS 1/2 queued for the subscriber beyond 1000 are dropped
    ("Outgoing messages are being dropped" in the broker log);
  - max_inflight_messages 20: also limits *incoming* unreleased QoS 2; beyond 20 the broker
    answers PUBREC with reason 0x97 (quota exceeded), which MQTT 3.1.1 can't carry, so paho
    completes the handshake and the message is silently discarded.
With both set to 0 everything arrives.

  python code/broker_queue_check.py                        # lab broker 192.168.1.4:1883, user uavpi
  python code/broker_queue_check.py --broker 127.0.0.1 --port 1884 --anonymous
Exit code 0 if every message arrived. The password comes from MQTT_PASSWORD or a prompt.
"""
import argparse, getpass, os, sys, time, uuid
import paho.mqtt.client as mqtt

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("--broker", default="192.168.1.4")
p.add_argument("--port", type=int, default=1883)
p.add_argument("--user", default="uavpi")
p.add_argument("--anonymous", action="store_true", help="no username/password (private test broker)")
p.add_argument("--n", type=int, default=3000)
p.add_argument("--sub-delay-ms", type=float, default=2.0)
p.add_argument("--timeout", type=float, default=60.0)
p.add_argument("--qos", default="1,2", help="QoS levels to test, e.g. '1,2'")
a = p.parse_args()

pw = None if a.anonymous else (os.environ.get("MQTT_PASSWORD") or getpass.getpass("MQTT password: "))

def run(qos):
    topic = f"queuecheck/{uuid.uuid4().hex[:8]}"
    got = set()
    last = [time.time()]

    def mk(cid):
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
        if pw is not None:
            c.username_pw_set(a.user, pw)
        return c

    def on_message(c, u, m):
        time.sleep(a.sub_delay_ms / 1000)
        got.add(int(m.payload))
        last[0] = time.time()

    sub = mk(f"qc-sub-{topic[-8:]}")
    sub.on_message = on_message
    subscribed = []
    sub.on_subscribe = lambda c, u, mid, rcs, props: subscribed.append(1)
    sub.connect(a.broker, a.port, 30)
    sub.subscribe(topic, qos=qos)
    sub.loop_start()
    t = time.time()
    while not subscribed and time.time() - t < 5:
        time.sleep(0.05)
    if not subscribed:
        raise SystemExit("subscribe failed")

    pub = mk(f"qc-pub-{topic[-8:]}")
    acked = [0]
    pub.on_publish = lambda c, u, mid, rc, props: acked.__setitem__(0, acked[0] + 1)
    pub.max_inflight_messages_set(0)        # 0 = no limit: send everything at once, like paho's resend burst
    pub.connect(a.broker, a.port, 30)
    pub.loop_start()
    t0 = time.time()
    for i in range(a.n):
        pub.publish(topic, str(i), qos=qos)
    while acked[0] < a.n and time.time() - t0 < a.timeout:
        time.sleep(0.05)
    t_pub = time.time() - t0
    while len(got) < a.n and time.time() - last[0] < 5 and time.time() - t0 < a.timeout:
        time.sleep(0.1)
    pub.disconnect(); pub.loop_stop(); sub.disconnect(); sub.loop_stop()
    print(f"{a.broker}:{a.port}: published {a.n} QoS {qos} (acked {acked[0]} in {t_pub:.1f} s), "
          f"received {len(got)} with a {a.sub_delay_ms} ms/message subscriber -> "
          f"{'OK, none dropped' if len(got) == a.n else f'{a.n - len(got)} DROPPED by the broker'}")
    return len(got) == a.n

ok = [run(int(q)) for q in a.qos.split(',')]
sys.exit(0 if all(ok) else 1)
