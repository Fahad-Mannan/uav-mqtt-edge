#!/usr/bin/env python3
"""Stand-in for publish_multi_sensor.py in local tests: same arguments and pi_log.csv format,
no sensors and no MQTT. Writes rows in real time at the nominal rates."""
import argparse, csv, json, time

p = argparse.ArgumentParser()
p.add_argument("--duration", type=float, default=3)
p.add_argument("--qos", type=int, default=1)
p.add_argument("--imu-hz", type=float, default=20)
p.add_argument("--nodelay", type=int, default=1)
p.add_argument("--log", required=True)
a = p.parse_args()
streams = [{"name": "bmp280", "hz": 2.0}, {"name": "mpu6050", "hz": a.imu_hz}, {"name": "ina219", "hz": 2.0}]
f = open(a.log, "w", newline="")
w = csv.writer(f)
w.writerow(["topic", "seq", "t_sample_ns", "t_pub_ns", "qos", "bytes", "sched_lag_ms", "payload"])
t0 = time.monotonic()
for s in streams:
    s["seq"], s["next"] = 0, t0
while True:
    s = min(streams, key=lambda x: x["next"])
    if s["next"] >= t0 + a.duration:
        break
    d = s["next"] - time.monotonic()
    if d > 0:
        time.sleep(d)
    ts = time.time_ns()
    msg = json.dumps({"uav_id": "uav_01", "sensor": s["name"], "seq": s["seq"], "t_sample_ns": ts,
                      "t_pub_ns": ts + 50_000, "data": {"x": 1.0}})
    w.writerow([f"uav/uav_01/{s['name']}", s["seq"], ts, ts + 50_000, a.qos, len(msg), 0.0, msg])
    s["seq"] += 1
    s["next"] = t0 + s["seq"] / s["hz"]
time.sleep(1.0)
f.close()
print("Sent:", {s["name"]: s["seq"] for s in streams})
