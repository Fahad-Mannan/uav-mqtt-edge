# Outage run A_q1_o60 (QoS 1, outage 60.01 s at +30.03 s)

Broker limits {'max_queued_messages': '0', 'max_inflight_messages': '0'}. Ping during cut answered: False; after: True; qdisc clean after: True.

Sent 4320, received unique 4320, lost 0, duplicate rows 0 (dup flag 0).

| phase | sent | rcvd | lost | rc 4 | lost with rc 0 | conn 0 | p50 ms | max ms |
|---|---|---|---|---|---|---|---|---|
| before | 703 | 703 | 0 | 0 | 0 | 0 | 4.95 | 8.9 |
| during | 1440 | 1440 | 0 | 676 | 0 | 700 | 30920.3 | 60828.6 |
| after | 2177 | 2177 | 0 | 21 | 0 | 21 | 4.85 | 940.9 |

Disconnect 30.81 s after the cut; reconnect 0.83 s after the restore; first delivery 0.83 s after; backlog flushed 0.94 s after; max latency of messages published during the outage 60.83 s; IMU peak AoI max 60.879 s (at 60.85 s after the cut). DRAIN: acked=4320 of 4320 in 0.05 s. Segment note: None.

Publisher events (s from the cut): SOCKET_OPEN nodelay=1 -29.24; CONNECT rc=Success -29.24; DISCONNECT rc=Keep alive timeout +30.81; DISCONNECT rc=Keep alive timeout +30.81; SOCKET_OPEN nodelay=1 +60.84; CONNECT rc=Success +60.84; DRAIN acked=4320 of 4320 in 0.05 s +150.77; FINISH  +150.77; DISCONNECT rc=Normal disconnection +150.77

Broker 'dropped' lines: 0
Broker client lines: 0

Throttled in the segment: {'0x0': np.int64(175)}. Chrony after the restore (s, LastRx, last sample): [(5.727434396743774, 2, '+84us['), (15.74545431137085, 1, '-24us['), (25.777802228927612, 3, '+207us['), (35.81071662902832, 1, '-443ns['), (45.84477400779724, 3, '+122us['), (55.87983560562134, 1, '-1752us[-1762us]'), (65.91436004638672, 3, '+69us['), (75.94813299179077, 1, '+258us[')]
