# Outage run A_q2_o30 (QoS 2, outage 30.01 s at +30.03 s)

Broker limits {'max_queued_messages': '0', 'max_inflight_messages': '0'}. Ping during cut answered: False; after: True; qdisc clean after: True.

Sent 3600, received unique 3600, lost 0, duplicate rows 0 (dup flag 0).

| phase | sent | rcvd | lost | rc 4 | lost with rc 0 | conn 0 | p50 ms | max ms |
|---|---|---|---|---|---|---|---|---|
| before | 703 | 703 | 0 | 0 | 0 | 0 | 5.43 | 12.0 |
| during | 721 | 721 | 0 | 0 | 0 | 0 | 16976.82 | 31923.2 |
| after | 2176 | 2176 | 0 | 0 | 0 | 25 | 5.58 | 1948.7 |

Disconnect 30.79 s after the cut; reconnect 1.79 s after the restore; first delivery 1.91 s after; backlog flushed 1.99 s after; max latency of messages published during the outage 31.92 s; IMU peak AoI max 31.973 s (at 31.92 s after the cut). DRAIN: acked=3600 of 3600 in 0.05 s. Segment note: None.

Publisher events (s from the cut): SOCKET_OPEN nodelay=1 -29.26; CONNECT rc=Success -29.25; DISCONNECT rc=Keep alive timeout +30.79; DISCONNECT rc=Keep alive timeout +30.79; SOCKET_OPEN nodelay=1 +31.80; CONNECT rc=Success +31.80; DRAIN acked=3600 of 3600 in 0.05 s +120.75; FINISH  +120.75; DISCONNECT rc=Normal disconnection +120.75

Broker 'dropped' lines: 0
Broker client lines: 0

Throttled in the segment: {'0x0': np.int64(146)}. Chrony after the restore (s, LastRx, last sample): [(5.6253063678741455, 37, '-194us['), (15.647403478622437, 2, '-103us['), (25.679759740829468, 8, '-257us['), (35.71526908874512, 2, '-130us['), (45.751813650131226, 4, '-75us['), (55.77973437309265, 14, '-75us['), (65.81422781944275, 24, '-75us['), (75.84831762313843, 2, '-167us[')]
