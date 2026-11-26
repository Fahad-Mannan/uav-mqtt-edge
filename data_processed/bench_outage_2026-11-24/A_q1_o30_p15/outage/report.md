# Outage run A_q1_o30_p15 (QoS 1, outage 30.01 s at +15.03 s)

Broker limits {'max_queued_messages': '0', 'max_inflight_messages': '0'}. Ping during cut answered: False; after: True; qdisc clean after: True.

Sent 3240, received unique 3240, lost 0, duplicate rows 0 (dup flag 0).

| phase | sent | rcvd | lost | rc 4 | lost with rc 0 | conn 0 | p50 ms | max ms |
|---|---|---|---|---|---|---|---|---|
| before | 342 | 342 | 0 | 0 | 0 | 0 | 4.64 | 8.8 |
| during | 721 | 721 | 0 | 0 | 0 | 0 | 31748.33 | 46688.0 |
| after | 2177 | 2177 | 0 | 0 | 0 | 24 | 5.2 | 16726.6 |

Disconnect 45.68 s after the cut; reconnect 16.68 s after the restore; first delivery 16.68 s after; backlog flushed 16.77 s after; max latency of messages published during the outage 46.69 s; IMU peak AoI max 46.738 s (at 46.7 s after the cut). DRAIN: acked=3240 of 3240 in 0.05 s. Segment note: None.

Publisher events (s from the cut): SOCKET_OPEN nodelay=1 -14.24; CONNECT rc=Success -14.19; DISCONNECT rc=Unspecified error +45.68; SOCKET_OPEN nodelay=1 +46.69; CONNECT rc=Success +46.70; DRAIN acked=3240 of 3240 in 0.05 s +120.81; FINISH  +120.81; DISCONNECT rc=Normal disconnection +120.81

Broker 'dropped' lines: 0
Broker client lines: 0

Throttled in the segment: {'0x0': np.int64(132)}. Chrony after the restore (s, LastRx, last sample): [(0.5934169292449951, 30, '+199us['), (10.614971399307251, 40, '+199us['), (20.64706516265869, 2, '-74us['), (30.666014671325684, 0, '-108us['), (40.69916272163391, 2, '-437us['), (50.718295097351074, 4, '-161us['), (60.751877546310425, 2, '-173us['), (70.78074717521667, 4, '+210us[')]
