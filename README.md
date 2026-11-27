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

## Additional checks

**MQTT 5 quota test** (`tests/test_mqtt5_quota.py`, laptop only). Can the publisher detect the QoS 2
messages that Mosquitto's default `max_inflight_messages 20` rejects?
- **Setup:** the test starts its own Mosquitto on a free localhost port with the default limits. The
  publisher sends 50 QoS 2 messages in one burst, with no client-side in-flight limit (like paho's
  resend after a reconnect).
- **Variants:** MQTT 3.1.1, MQTT 5, and MQTT 5 with the client's in-flight limit set to the
  broker's Receive Maximum.
- **Recorded per message:** `on_publish` reason code, `is_published()`, `wait_for_publish()` and
  delivery to a subscriber. PUBREC/PUBCOMP reason codes come from a loopback capture and the broker
  debug log.
- **Needs:** Mosquitto 2.0.18, `dumpcap` with capture rights (e.g. group `wireshark`), and a Python
  with the paho version to test.

```
python tests/test_mqtt5_quota.py --python /path/to/venv-with-paho-2.1/bin/python [--reps 3]
```

Raw outputs (captures, broker logs) go to `data/mqtt5_check/`, which is not tracked. The results are
in `data_processed/mqtt5_check/` (`notes.md`, `summary.md`); 3 repeats each, identical:

| Variant | Sent | PUBREC rc 0 / 0x97 | Publisher believed delivered | Actually delivered |
|---|---|---|---|---|
| MQTT 3.1.1 | 50 | 20 / 30 | 50 | 20 |
| MQTT 5 | 50 | 35 / 15 | 50 | 35 |
| MQTT 5, in-flight limit = Receive Maximum (20) | 50 | 50 / 0 | 50 | 50 |

- **MQTT 5 puts 0x97 on the wire, but paho-mqtt 2.1.0 (and 2.2.0) ignores the PUBREC reason code.**
  It then sends PUBREL anyway, Mosquitto answers with a success PUBCOMP, and the publisher reports
  every rejected message as delivered. So switching to MQTT 5 alone does not make the loss detectable
  with paho.
- **Ways to avoid the loss:** honour the broker's Receive Maximum, or set `max_inflight_messages 0`
  on the broker (as in `config/mosquitto-lab.conf`).
- **MQTT 5 accepted 35, not 20.** After the 20th message Mosquitto 2.0.18 alternated between
  rejecting and accepting; the cause is not established.

**Bootstrap confidence intervals** (`analysis/bootstrap_ci.py`). 95% intervals for the latency
statistics:
- **Flights:** share > 20 ms, p50 and p95 per flight x QoS x RSSI band, as in `link_bands/`.
- **Comparisons:** QoS 2 vs QoS 0/1, and weak vs strong band, per flight and pooled over the flights.
- **Bench baseline:** `base_final` p95, p99 and share > 20 ms, with and without scan windows.

Method:
- **Bootstrap:** moving-block, circular within each contiguous stretch of a cell, because late
  messages are clustered in time. Blocks of 2 s, plus 1 s and 5 s as a sensitivity check; 10,000
  resamples; seed 20261126; percentile intervals.
- **Bench:** a run-level bootstrap as well.
- **Inputs:** it reads `data_processed/` (or `$UAV_MQTT_DATA`) and checks its point estimates
  against the published tables.

```
python analysis/bootstrap_ci.py            # about 2.5 min; writes data_processed/ci/
```

Results are in `data_processed/ci/` (`summary.md` first):
- **QoS 2 vs QoS 0/1:** pooled over the four flights, the QoS 2 share over 20 ms in the -65 to -75 dBm
  band is higher than QoS 1's by 2.1 percentage points (95% CI 0.8-4.0) and QoS 0's by 2.4 (0.9-4.2).
- **Band effect:** QoS 2 in that band is 2.5 points (1.4-4.3) above QoS 2 in the -55 to -65 band.
- These intervals exclude 0 at all three block lengths. Several per-flight differences are
  inconclusive or depend on the block length, and all cells with fewer than 100 messages or 10 blocks
  are flagged as too small.

**Weak-link bench test (QoS 2 round trip)** (`code/run_weak_link.py`, `analysis/weak_link_qos2.py`,
`analysis/weak_link_ci.py`). Does QoS 2's extra latency come from its extra radio round trip, and
does that round trip grow on a weaker link? This backs Section VI.G.5 and Table 10 of the paper.
- **Setup:** the Pi is static at three positions: about 2 m line of sight (about -42 dBm), through
  walls (about -69 dBm), and further through walls (about -80 dBm, 7-14 Mbit/s).
- **Run per position:** one `run_field.py` flight-mode run of 6 rounds x QoS 0/1/2 x 20 s, with the
  QoS order rotated every round. The laptop captures packets on the wired and loopback interfaces,
  with MQTT CONNECT segments filtered out so no credential is stored.
- **Latency split:** each message's latency is split into three parts from the capture:
  - Pi -> broker (Pi publish -> laptop NIC + broker turnaround);
  - the PUBREC -> PUBREL radio round trip (QoS 2 only);
  - broker -> logger.

  A clock-free radio round trip (broker reply -> the Pi's TCP ACK) is also reported.
- **CIs:** `weak_link_ci.py` gives 95% moving-block bootstrap intervals, with the same method as
  `bootstrap_ci.py` (2 s blocks, plus 1 s and 5 s as a sensitivity check). They cover:
  - QoS 2 vs QoS 0 and QoS 1, for p95 and share > 20 ms;
  - the change from the first position in the round trip's median and p95;
  - the change from the first position in the QoS 2 - QoS 1 p95 gap.

```
python code/run_weak_link.py --position p2m --distance-m 2 --notes "..."   # one run per position; --dry-run prints the plan
python analysis/weak_link_qos2.py data/weak_link_p2m/r1 data/weak_link_wall1/r1 data/weak_link_far1/r1
python analysis/weak_link_ci.py data/weak_link_p2m/r1 data/weak_link_wall1/r1 data/weak_link_far1/r1 --block-s 2,1,5
```

The first command needs the Pi and the lab broker (the MQTT password comes from a prompt or
`MQTT_PASSWORD`). The raw runs and captures are not included. The analyses write to
`<run>/weak_link/` and `data/weak_link_summary/`.

## Licence

MIT (see `LICENSE`).
