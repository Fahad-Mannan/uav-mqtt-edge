# Outage run A_q0_o30 (QoS 0, outage 30.01 s at +30.03 s)

Broker limits {'max_queued_messages': '0', 'max_inflight_messages': '0'}. Ping during cut answered: False; after: True; qdisc clean after: True.

Sent 3600, received unique 2892, lost 708, duplicate rows 0 (dup flag 0).

| phase | sent | rcvd | lost | rc 4 | lost with rc 0 | conn 0 | p50 ms | max ms |
|---|---|---|---|---|---|---|---|---|
| before | 702 | 702 | 0 | 0 | 0 | 0 | 5.38 | 40571.6 |
| during | 720 | 57 | 663 | 0 | 663 | 0 | 39330.71 | 40521.8 |
| after | 2178 | 2133 | 45 | 25 | 20 | 25 | 5.3 | 8.3 |

Disconnect 30.85 s after the cut; reconnect 1.86 s after the restore; first delivery 1.88 s after; backlog flushed 10.56 s after; max latency of messages published during the outage 40.52 s; IMU peak AoI max 31.952 s (at 31.9 s after the cut). DRAIN: None. Segment note: None.

Publisher events (s from the cut): SOCKET_OPEN nodelay=1 -29.16; CONNECT rc=Success -29.16; DISCONNECT rc=Keep alive timeout +30.85; DISCONNECT rc=Keep alive timeout +30.85; SOCKET_OPEN nodelay=1 +31.86; CONNECT rc=Success +31.88; FINISH  +121.80; DISCONNECT rc=Normal disconnection +121.80

Broker 'dropped' lines: 0
Broker client lines: 4
    1795591556 New client connected from 192.168.1.3:44055 as auto-4536E5AB-23C2-43A5-A60E-3D7895C56C0A (p2, c1, k30, u'uavpi').
    1795591617 New client connected from 192.168.1.3:38347 as auto-013B1CBB-449C-46A8-5DC2-3E1D489B79DE (p2, c1, k30, u'uavpi').
    1795591707 Client auto-013B1CBB-449C-46A8-5DC2-3E1D489B79DE disconnected.
    1795591750 Client auto-5DCF85AB-3028-AD52-5915-B98932FCD999 disconnected.

Throttled in the segment: {'0x0': np.int64(147)}. Chrony after the restore (s, LastRx, last sample): [(5.754432439804077, 38, '-27us['), (15.786534547805786, 3, '-20us['), (25.821020126342773, 1, '-1078us[-1118us]'), (35.856136083602905, 3, '+2740ns['), (45.88892841339111, 5, '-424us['), (55.917235136032104, 3, '-3983ns['), (65.94863939285278, 5, '-76us['), (75.97784638404846, 7, '+37us[')]
