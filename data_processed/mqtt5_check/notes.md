# MQTT 5 quota check (2026-11-26, `tests/test_mqtt5_quota.py`)

Laptop only. A private Mosquitto 2.0.18 on a free 127.0.0.1 port with default limits; the system
broker on 1883 was not touched. Publisher paho-mqtt 2.1.0 (scratch venv). 50 QoS 2 messages in one
burst, client in-flight limit 0 (unlimited), manual network loop, so all 50 PUBLISHes reach the
broker before any PUBREL. The subscriber is MQTT 3.1.1, QoS 2, 2 ms per message. 3 repeats per
variant, interleaved. The reason codes come from the loopback capture (dumpcap) and from the broker
debug log, which agree.

| Variant | Sent | PUBREC rc 0 / 0x97 | 0x97 visible on the wire | Publisher believed delivered | Actually delivered | Rejected messages the publisher could detect |
|---|---|---|---|---|---|---|
| v311 | 50 | 20 / 30 (broker log only) | no: a 3.1.1 PUBREC has no reason field | 50 | 20 (messages 1-20) | 0 of 30 |
| v5 | 50 | 35 / 15 | yes, 15 x 0x97 | 50 | 35 | 0 of 15 with the paho API |
| v5_rm (extra: client in-flight limit = CONNACK Receive Maximum 20) | 50 | 50 / 0 | – | 50 | 50 | nothing rejected |

Identical in all 3 repeats.

- **3.1.1:** reproduces the reported pattern exactly: 1-20 accepted, 21-50 rejected with 0x97 (in the
  broker log), 20 delivered, and the publisher sees success for all 50.
- **MQTT 5 puts 0x97 on the wire, but paho 2.1.0 ignores it** (`_handle_pubrec` parses the reason code
  and drops it; paho 2.2.0 is the same, with a TODO in the code). paho then sends PUBREL anyway, which
  MQTT 5 does not allow after a PUBREC >= 0x80. Mosquitto answers with a PUBCOMP carrying no reason
  code (success). So `on_publish` reports Success, `is_published()` is True and `wait_for_publish()`
  returns normally for every rejected message.
  - **Unexpected:** I predicted PUBCOMP 0x92 (packet identifier not found), which would have reached
    `on_publish`; Mosquitto 2.0.18 sent success.
- **Unexpected: under MQTT 5 the broker accepted 35, not 20.**
  - Rejections alternate after the 20th: m21 rejected, m22 accepted, m23 rejected, and so on.
  - Every PUBREL arrived after m50, so it is not client timing.
  - Hypothesis (Mosquitto source not checked): its MQTT 5 receive-quota accounting gives a slot back
    on each 0x97 rejection.
  - Under 3.1.1 the same burst gives a strict 20 / 30.
- **What would make loss detectable or avoidable:**
  - **Detect:** an MQTT 5 client that acts on the PUBREC reason code. Not paho 2.1 or 2.2 out of the
    box; a subclass or patch of `_handle_pubrec` would be needed (untested).
  - **Avoid:** a client that honours the broker's Receive Maximum (v5_rm: 50/50), or the broker fix
    already used in the lab (`max_inflight_messages 0`).
- **Trial runs, not kept:** with a threaded network loop (`loop_start`), PUBRELs interleave with the
  burst and free slots, so the counts depend on timing (trial: 24 accepted under 3.1.1, 37 under MQTT 5).
  The kept runs use the manual loop for a deterministic burst.
- **Source of the "1-20 / 21-50" pattern:** not found as a script or data in the repos before this
  test. The earlier evidence is `broker_queue_check.py` (3000 messages) and outage run `B_q2_o60`
  (20 of 1440 accepted).
