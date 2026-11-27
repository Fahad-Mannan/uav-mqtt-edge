# MQTT 5 vs 3.1.1: detecting incoming-QoS-2 quota rejections

50 QoS 2 messages at once, private Mosquitto with default limits, subscriber delay 2 ms.

| variant | rep | paho | connack_receive_maximum | sent | pubrec_rc0_log | pubrec_0x97_log | pubrec_0x97_wire | pubrec_wire_no_rc_field | pubrel_after_0x97 | pubcomp_rc_after_0x97 | is_published_true | on_publish_success | believed_delivered | delivered | rejected_flagged_by_on_publish | on_publish_rc_for_rejected |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v311 | 1 | 2.1.0 | nan | 50 | 20 | 30 | 0 | 50 | 30 | no field (0) | 50 | 50 | 50 | 20 | 0 | Success |
| v5 | 1 | 2.1.0 | 20.0 | 50 | 35 | 15 | 15 | 35 | 15 | no field (0) | 50 | 50 | 50 | 35 | 0 | Success |
| v5_rm | 1 | 2.1.0 | 20.0 | 50 | 50 | 0 | 0 | 50 | 0 |  | 50 | 50 | 50 | 50 | 0 |  |
| v311 | 2 | 2.1.0 | nan | 50 | 20 | 30 | 0 | 50 | 30 | no field (0) | 50 | 50 | 50 | 20 | 0 | Success |
| v5 | 2 | 2.1.0 | 20.0 | 50 | 35 | 15 | 15 | 35 | 15 | no field (0) | 50 | 50 | 50 | 35 | 0 | Success |
| v5_rm | 2 | 2.1.0 | 20.0 | 50 | 50 | 0 | 0 | 50 | 0 |  | 50 | 50 | 50 | 50 | 0 |  |
| v311 | 3 | 2.1.0 | nan | 50 | 20 | 30 | 0 | 50 | 30 | no field (0) | 50 | 50 | 50 | 20 | 0 | Success |
| v5 | 3 | 2.1.0 | 20.0 | 50 | 35 | 15 | 15 | 35 | 15 | no field (0) | 50 | 50 | 50 | 35 | 0 | Success |
| v5_rm | 3 | 2.1.0 | 20.0 | 50 | 50 | 0 | 0 | 50 | 0 |  | 50 | 50 | 50 | 50 | 0 |  |
