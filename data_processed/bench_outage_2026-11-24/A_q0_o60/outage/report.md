# Outage run A_q0_o60 (QoS 0, outage 60.01 s at +30.03 s)

Broker limits {'max_queued_messages': '0', 'max_inflight_messages': '0'}. Ping during cut answered: False; after: True; qdisc clean after: True.

Sent 4320, received unique 2830, lost 1490, duplicate rows 0 (dup flag 0).

| phase | sent | rcvd | lost | rc 4 | lost with rc 0 | conn 0 | p50 ms | max ms |
|---|---|---|---|---|---|---|---|---|
| before | 703 | 703 | 0 | 0 | 0 | 0 | 5.12 | 6.0 |
| during | 1440 | 0 | 1440 | 702 | 738 | 702 | None | None |
| after | 2177 | 2127 | 50 | 50 | 0 | 50 | 5.23 | 7.6 |

Disconnect 30.77 s after the cut; reconnect 2.07 s after the restore; first delivery 2.11 s after; backlog flushed None s after; max latency of messages published during the outage None s; IMU peak AoI max 62.155 s (at 62.12 s after the cut). DRAIN: None. Segment note: None.

Publisher events (s from the cut): SOCKET_OPEN nodelay=1 -29.24; CONNECT rc=Success -29.24; DISCONNECT rc=Keep alive timeout +30.77; DISCONNECT rc=Keep alive timeout +30.77; SOCKET_OPEN nodelay=1 +62.08; CONNECT rc=Success +62.08; FINISH  +151.72; DISCONNECT rc=Normal disconnection +151.72

Broker 'dropped' lines: 0
Broker client lines: 0

Throttled in the segment: {'0x0': np.int64(176)}. Chrony after the restore (s, LastRx, last sample): [(5.766186475753784, 1, '-955us['), (15.800755500793457, 3, '-39us[-5420ns]'), (25.83270812034607, 1, '+8312ns['), (35.853811264038086, 3, '-135us['), (45.883936643600464, 1, '-283us['), (55.916086196899414, 3, '+18us['), (65.9443097114563, 0, '-296us['), (75.96425867080688, 6, '-231us[')]
