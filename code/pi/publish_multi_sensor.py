#!/usr/bin/env python3
"""Multi-sensor MQTT publisher (baseline version) for the UAV edge module.

Each sensor has its own topic and rate. Every message carries:
  t_sample_ns - time the reading was taken
  t_pub_ns    - time just before the message is encoded and published
Every message is also written to a local CSV log on the Pi, with paho's return code (rc) and
whether the client was connected (conn) at publish time.

Link loss (paho-mqtt 2.1 behaviour, see tests/test_outage.py):
- The publisher keeps running; paho's network thread reconnects on its own, retrying every
  1-2 s (reconnect_delay_set(1, 2); paho's default backs off to 120 s).
- connect_async: a run that starts while the broker is unreachable still publishes and logs.
- QoS 0 published while disconnected: rc 4 (MQTT_ERR_NO_CONN), dropped by paho. QoS 0 written to
  a dead socket before paho notices (keepalive 30 s: 30-60 s) is lost when the socket closes.
- QoS 1/2 published while disconnected: also rc 4, but the message IS kept in paho's outgoing
  store and sent after the next CONNACK (same payload, so same seq). So every QoS 1/2 publish
  counts towards the drain target, whatever its rc (except MQTT_ERR_QUEUE_SIZE).
- TCP_NODELAY is set on every new socket (on_socket_open), not only the first one.
- At the end, wait up to --drain-s for every QoS 1/2 message to be acknowledged (PUBACK/PUBCOMP)
  before disconnecting; disconnect() would discard what is still queued.
Connection events go to stdout (publisher.out): SOCKET_OPEN, CONNECT, DISCONNECT, DRAIN, FINISH.
"""
import argparse, csv, getpass, json, os, random, socket, threading, time
import paho.mqtt.client as mqtt

p = argparse.ArgumentParser()
p.add_argument("--broker", default="192.168.1.4")
p.add_argument("--port", type=int, default=1883)
p.add_argument("--user", default="uavpi")
p.add_argument("--uav", default="uav_01")
p.add_argument("--duration", type=float, default=60.0, help="seconds")
p.add_argument("--qos", type=int, default=1, choices=[0, 1, 2])
p.add_argument("--imu-hz", type=float, default=20.0)
p.add_argument("--bmp-hz", type=float, default=2.0)
p.add_argument("--ina-hz", type=float, default=2.0)
p.add_argument("--log", default=None, help="local CSV log path")
p.add_argument("--nodelay", type=int, default=0, choices=[0, 1], help="1 = set TCP_NODELAY")
p.add_argument("--drain-s", type=float, default=30.0,
               help="at the end, wait up to this long for QoS 1/2 acknowledgements")
p.add_argument("--connect-wait-s", type=float, default=10.0,
               help="wait this long for the first CONNACK before publishing anyway")
p.add_argument("--fake-sensors", action="store_true", help="synthetic readings (laptop tests, no I2C)")
a = p.parse_args()

# Sensors
if a.fake_sensors:
    rnd = random.Random(1)
    read_bmp = lambda: {"temperature_c": 25.0 + rnd.random(), "pressure_hpa": 840.0 + rnd.random()}
    read_imu = lambda: {"accel_m_s2": [rnd.random(), rnd.random(), 9.8], "gyro_rad_s": [0.0, 0.0, rnd.random()]}
    read_ina = lambda: {"bus_voltage_v": 0.9, "current_ma": 0.0, "power_mw": 0.0}
else:
    import board
    import adafruit_bmp280, adafruit_mpu6050, adafruit_ina219
    i2c = board.I2C()
    bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=0x77)
    bmp.mode = adafruit_bmp280.MODE_NORMAL      # measure continuously: reads take ~2 ms
    bmp.overscan_pressure = adafruit_bmp280.OVERSCAN_X4
    bmp.overscan_temperature = adafruit_bmp280.OVERSCAN_X1
    mpu = adafruit_mpu6050.MPU6050(i2c)
    ina = adafruit_ina219.INA219(i2c)
    read_bmp = lambda: {"temperature_c": bmp.temperature, "pressure_hpa": bmp.pressure}
    read_imu = lambda: {"accel_m_s2": mpu.acceleration, "gyro_rad_s": mpu.gyro}
    read_ina = lambda: {"bus_voltage_v": ina.bus_voltage, "current_ma": ina.current, "power_mw": ina.power}

streams = [
    {"name": "bmp280", "hz": a.bmp_hz, "read": read_bmp},
    {"name": "mpu6050", "hz": a.imu_hz, "read": read_imu},
    {"name": "ina219", "hz": a.ina_hz, "read": read_ina},
]

# MQTT
password = os.environ.get("MQTT_PASSWORD") or getpass.getpass("MQTT password: ")
connected = threading.Event()
first_rc = [None]
acked = [0]                                       # QoS 1/2: PUBACK / PUBCOMP received

def log_event(text):
    print(f"{text} t={time.time():.3f}", flush=True)

def on_socket_open(client, userdata, sock):       # every new socket, including reconnects
    if a.nodelay:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    log_event(f"SOCKET_OPEN nodelay={sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)}")

def on_connect(client, userdata, flags, reason_code, properties):
    if first_rc[0] is None:
        first_rc[0] = reason_code
    connected.set()
    log_event(f"CONNECT rc={reason_code}")

def on_disconnect(client, userdata, flags, reason_code, properties):
    log_event(f"DISCONNECT rc={reason_code}")

def on_publish(client, userdata, mid, reason_code, properties):
    acked[0] += 1                                 # QoS 0: fires when written; only used for QoS > 0

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set(a.user, password)
client.reconnect_delay_set(1, 2)
client.on_socket_open = on_socket_open
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_publish = on_publish
client.connect_async(a.broker, a.port, 30)
client.loop_start()
if connected.wait(a.connect_wait_s):
    if first_rc[0] != 0:
        client.loop_stop()
        raise SystemExit(f"MQTT connection refused: {first_rc[0]}")
    print("Connected to MQTT broker", flush=True)
else:
    log_event(f"NOT CONNECTED after {a.connect_wait_s:.0f} s: publishing anyway (paho keeps retrying)")

# Local log: a full record of everything sent
log_path = a.log or os.path.expanduser(
    f"~/mqtt_uav_test/pi_log_{time.strftime('%Y%m%d_%H%M%S')}.csv")
f = open(log_path, "w", newline="")
w = csv.writer(f)
w.writerow(["topic", "seq", "t_sample_ns", "t_pub_ns", "qos", "bytes", "sched_lag_ms", "rc", "conn", "payload"])

t0 = time.monotonic()
end = t0 + a.duration
for s in streams:
    s["seq"] = 0
    s["next"] = t0
print(f"Publishing for {a.duration:.0f} s at QoS {a.qos}; local log: {log_path}", flush=True)

to_ack = 0                                        # QoS 1/2 messages paho holds for delivery
rc_counts = {}
try:
    while True:
        s = min(streams, key=lambda x: x["next"])
        if s["next"] >= end:
            break
        delay = s["next"] - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        lag_ms = max(0.0, -delay) * 1000
        reading = s["read"]()
        t_sample = time.time_ns()
        payload = {"uav_id": a.uav, "sensor": s["name"], "seq": s["seq"],
                   "t_sample_ns": t_sample, "t_pub_ns": time.time_ns(), "data": reading}
        msg = json.dumps(payload)
        topic = f"uav/{a.uav}/{s['name']}"
        conn = int(client.is_connected())
        rc = int(client.publish(topic, msg, qos=a.qos).rc)
        rc_counts[rc] = rc_counts.get(rc, 0) + 1
        if a.qos > 0 and rc in (mqtt.MQTT_ERR_SUCCESS, mqtt.MQTT_ERR_NO_CONN):
            to_ack += 1                           # queued by paho even when rc is NO_CONN
        w.writerow([topic, s["seq"], t_sample, payload["t_pub_ns"], a.qos, len(msg),
                    round(lag_ms, 3), rc, conn, msg])
        s["seq"] += 1
        s["next"] = t0 + s["seq"] / s["hz"]
except KeyboardInterrupt:
    print("Stopped by user", flush=True)
finally:
    f.flush()
    t_drain = time.monotonic()
    if a.qos > 0:
        while acked[0] < to_ack and time.monotonic() - t_drain < a.drain_s:
            time.sleep(0.05)
        log_event(f"DRAIN acked={acked[0]} of {to_ack} in {time.monotonic() - t_drain:.2f} s"
                  f"{'' if acked[0] >= to_ack else ' (TIMEOUT: rest lost)'}")
    else:
        time.sleep(1.0)                           # let the last QoS 0 writes go out
    log_event("FINISH")                           # DISCONNECT events after this are our own
    client.disconnect()
    client.loop_stop()
    f.close()
    print("Sent:", {s["name"]: s["seq"] for s in streams}, "publish rc counts:", rc_counts, flush=True)
