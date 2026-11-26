# Outage run A_q2_o60 (QoS 2, outage 60.01 s at +30.03 s)

Broker limits {'max_queued_messages': '0', 'max_inflight_messages': '0'}. Ping during cut answered: False; after: True; qdisc clean after: True.

Sent 4320, received unique 4320, lost 0, duplicate rows 0 (dup flag 0).

| phase | sent | rcvd | lost | rc 4 | lost with rc 0 | conn 0 | p50 ms | max ms |
|---|---|---|---|---|---|---|---|---|
| before | 703 | 703 | 0 | 0 | 0 | 0 | 5.9 | 12.4 |
| during | 1440 | 1440 | 0 | 676 | 0 | 700 | 33187.37 | 63048.2 |
| after | 2177 | 2177 | 0 | 70 | 0 | 70 | 5.98 | 3204.2 |

Disconnect 30.81 s after the cut; reconnect 2.87 s after the restore; first delivery 3.05 s after; backlog flushed 3.21 s after; max latency of messages published during the outage 63.05 s; IMU peak AoI max 63.098 s (at 63.07 s after the cut). DRAIN: acked=4320 of 4320 in 0.05 s. Segment note: None.

Publisher events (s from the cut): SOCKET_OPEN nodelay=1 -29.24; CONNECT rc=Success -29.24; DISCONNECT rc=Keep alive timeout +30.81; DISCONNECT rc=Keep alive timeout +30.81; SOCKET_OPEN nodelay=1 +62.88; CONNECT rc=Success +62.88; DRAIN acked=4320 of 4320 in 0.05 s +150.77; FINISH  +150.77; DISCONNECT rc=Normal disconnection +150.77

Broker 'dropped' lines: 0
Broker client lines: 0

Throttled in the segment: {'0x0': np.int64(176)}. Chrony after the restore (s, LastRx, last sample): [(5.738241910934448, 69, '+92us['), (15.759607553482056, 2, '-239us['), (25.78639316558838, 4, '-402us['), (35.80719065666199, 6, '-247us['), (45.83758759498596, 8, '-132us['), (55.869494676589966, 10, '-274us['), (65.89962911605835, 7, '-218us['), (75.93141555786133, 1, '-53us[')]
