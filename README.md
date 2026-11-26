# Scalable MQTT-Based Raspberry Pi Edge Framework for Real-Time Multi-Sensor UAV Data Streaming

Code, processed data and figures for the paper of the same title.

A Raspberry Pi 4B on a quadcopter streams IMU (20 Hz), barometer (2 Hz) and power-monitor (2 Hz)
readings over MQTT, through a 5 GHz Wi-Fi router, to a Mosquitto broker on a ground-station laptop.
The repository measures how that link behaves: latency, delivery, jitter, throughput and Age of
Information at QoS 0, 1 and 2.
- **Settings:** on the bench and in out-and-back flights up to ~180 m.
- **Mechanisms identified:** Nagle's algorithm on the broker's sockets (QoS 2 tail), periodic Wi-Fi
  background scans (latency spike episodes), and what happens to each QoS level during a link outage,
  including messages that are acknowledged but silently dropped under Mosquitto's default in-flight
  limit.

## Citation

F. Mannan and M. Hassanalian, "Scalable MQTT-Based Raspberry Pi Edge Framework for Real-Time
Multi-Sensor UAV Data Streaming," *AIAA SciTech Forum 2027*, AIAA paper number to be added.

## Hardware and software

| Part | Used in the paper |
|---|---|
| Edge computer | Raspberry Pi 4B, 64-bit Raspberry Pi OS (Debian 13), Python 3.13, paho-mqtt 2.1.0 |
| Sensors (I²C) | MPU6050 (IMU), BMP280 (pressure / temperature, address 0x77), INA219 (address 0x40; connected over I²C but not wired to a supply line, so its readings are near zero) |
| Wi-Fi | NETGEAR WAX204, 5 GHz channel 153 (5765 MHz), WPA2; the Pi's Wi-Fi power save off, BSSID-locked from 2026-11-23 (no background scans) |
| Ground station | Ubuntu 24.04 laptop on Ethernet to the router; Mosquitto 2.0.18; Python 3.12; chrony serving time to the Pi |
| Vehicle | Quadcopter with a Pixhawk (ArduPilot) and M10 GPS; Pixhawk logs give position and flight state |
| Pi power in flight | 3S LiPo → LM2596 buck converter |

Laptop Python packages: `requirements.txt`. Pi packages: `requirements-pi.txt`.

## Folder layout

```
code/            publisher, logger and run control
  pi/            runs on the Pi: publish_multi_sensor.py (publisher), flight_launcher.py, side_log.sh
  logger.py      laptop subscriber, one CSV row per message
  run_campaign.py, run_field.py, campaign_lib.py, flight_lib.py   bench campaigns and field / flight runs over SSH
  bench_outage.py, broker_queue_check.py, broker_coalesce_test.py  outage and broker tests
analysis/        metrics, position, link-band, outage and figure scripts
tests/           laptop-only tests (no Pi needed)
paper_figs/      the paper's data figures (PNG 300 dpi and PDF)
data_processed/  processed outputs behind the paper's tables and figures (see below)
config/          example Mosquitto and chrony settings
```

## Running the measurements

The MQTT password is never stored. Every script reads it from a prompt, or from the `MQTT_PASSWORD`
environment variable if set.

**Broker** (laptop): Mosquitto with password authentication, `set_tcp_nodelay true`,
`max_queued_messages 0` and `max_inflight_messages 0` (see `config/mosquitto-lab.conf`). The two
limits matter: with Mosquitto's defaults, a QoS 2 backlog after an outage is acknowledged to the
publisher but silently dropped.

**Publisher** (on the Pi, in a virtualenv with `requirements-pi.txt`):

```
python code/pi/publish_multi_sensor.py --broker <laptop-ip> --user <mqtt-user> --qos 1 --duration 60 --nodelay 1
```

Add `--fake-sensors` to run without the I²C sensors (laptop tests).

**Logger** (laptop):

```
python code/logger.py --broker <laptop-ip> --user <mqtt-user> --qos 2 --out rx.csv --nodelay 1
```

The logger subscribes at QoS 2, so the publisher's QoS sets the delivery level.

**Campaigns and field runs** (laptop; start the publisher on the Pi over SSH and collect the logs):

```
python code/run_campaign.py --name base_final --qos 0,1,2 --repeats 5 --duration 60 [--plan-only]
python code/run_field.py --session <session> --label <run> --qos 1 --duration 300 [--dry-run]
python code/run_field.py --session <session> --label f3 --schedule "qos0:20,qos1:20,qos2:20" --points ob --start-delay-s 65   # flight mode
```

- **Lab-specific settings:** the Pi's SSH target, the broker and router addresses, and the working
  folders are set at the top of `code/campaign_lib.py` and `code/run_campaign.py`, and as defaults in
  the publisher and logger. Change them for another setup.
- **Raw data location:** raw runs are written to `~/uav-mqtt/data/<campaign>/`, which most analysis
  scripts read.
- **Before each field run:** `run_field.py` checks the Pi's power state and its chrony sync to the
  laptop.

**Tests** (laptop only; some start a private Mosquitto on 127.0.0.1):

```
python tests/test_flight.py
python tests/test_outage.py --quick
```

## Regenerating the paper figures

From the repository root, with `requirements.txt` installed:

```
python analysis/make_figures.py            # all figures (2-8) into paper_figs/
python analysis/make_figures.py 3 7        # selected figures
```

`make_figures.py` reads only `data_processed/`. To use another data folder, set `UAV_MQTT_DATA`; to
write the figures elsewhere, set `UAV_MQTT_FIGS`. It prints n per series and the key numbers behind
each figure.

## Processed data (`data_processed/`)

Processed outputs only. GPS latitude/longitude and absolute positions are removed; distances from
the router, altitude above takeoff, RSSI, timing and latency are kept.

- **Bench metrics:** `metrics_runs.csv`, `metrics_pooled.csv` and `metrics.md` per campaign
  (`analysis/metrics.py`).
- **Per-message logs:** the laptop logger's per-message files `rx.csv` / `rx_all.csv` (timing, topic,
  QoS, sequence number, size; no payload) for the runs used in the figures.
- **Processed Pi logs:**
  - `scans.csv`: Wi-Fi scan start/end times;
  - `rssi.csv`: the Pi's signal, bit-rate and failed-transmission counters over time;
  - `ping_pi.csv`: ping round-trip times;
  - `sent.csv`: the publisher's send log without payload.
- **Flights:** `position/` (each message with its distance from the router and altitude; summary
  tables by position) and the Pixhawk-derived flight state (`pixhawk/*_state/`).
- **Link bands:** `link_bands/` (latency and Wi-Fi counters by RSSI band and by out-and-back leg).
- **Bench outage:** `bench_outage_2026-11-24/` (outage timing, per-run reports, sent and received
  messages).

Raw packet captures, Pi and laptop system journals, raw Wi-Fi and clock logs, publisher payload logs
and Pixhawk logs are not included. They are available from the authors on request.

## Licence

MIT (see `LICENSE`).
