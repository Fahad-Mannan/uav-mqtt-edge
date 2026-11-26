# Outage run A_q1_o30 (QoS 1, outage 30.01 s at +30.03 s)

Broker limits {'max_queued_messages': '0', 'max_inflight_messages': '0'}. Ping during cut answered: False; after: True; qdisc clean after: True.

Sent 3600, received unique 3600, lost 0, duplicate rows 0 (dup flag 0).

| phase | sent | rcvd | lost | rc 4 | lost with rc 0 | conn 0 | p50 ms | max ms |
|---|---|---|---|---|---|---|---|---|
| before | 703 | 703 | 0 | 0 | 0 | 0 | 4.84 | 6.5 |
| during | 720 | 720 | 0 | 0 | 0 | 0 | 16869.39 | 31813.4 |
| after | 2177 | 2177 | 0 | 0 | 0 | 25 | 4.95 | 1872.7 |

Disconnect 30.81 s after the cut; reconnect 1.82 s after the restore; first delivery 1.82 s after; backlog flushed 1.88 s after; max latency of messages published during the outage 31.81 s; IMU peak AoI max 31.863 s (at 31.83 s after the cut). DRAIN: acked=3600 of 3600 in 0.05 s. Segment note: None.

Publisher events (s from the cut): SOCKET_OPEN nodelay=1 -29.24; CONNECT rc=Success -29.23; DISCONNECT rc=Keep alive timeout +30.81; DISCONNECT rc=Keep alive timeout +30.81; SOCKET_OPEN nodelay=1 +31.83; CONNECT rc=Success +31.83; DRAIN acked=3600 of 3600 in 0.05 s +120.77; FINISH  +120.77; DISCONNECT rc=Normal disconnection +120.77

Broker 'dropped' lines: 0
Broker client lines: 0

Throttled in the segment: {'0x0': np.int64(146)}. Chrony after the restore (s, LastRx, last sample): [(5.7655088901519775, 2, '-1548us[-1547us]'), (15.781639099121094, 0, '-1609us[-1618us]'), (25.799803733825684, 2, '-46us[-1738ns]'), (35.83077645301819, 4, '-1696us[-1702us]'), (45.86442422866821, 2, '-1297us[-1301us]'), (55.892890214920044, 4, '-122us['), (65.9251070022583, 1, '-266us['), (75.96247887611389, 3, '-260us[')]
