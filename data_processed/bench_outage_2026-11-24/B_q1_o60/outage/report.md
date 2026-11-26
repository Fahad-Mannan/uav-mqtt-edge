# Outage run B_q1_o60 (QoS 1, outage 60.01 s at +30.03 s)

Broker limits {'max_queued_messages': 'default', 'max_inflight_messages': 'default'}. Ping during cut answered: False; after: True; qdisc clean after: True.

Sent 4320, received unique 4320, lost 0, duplicate rows 1 (dup flag 0).

| phase | sent | rcvd | lost | rc 4 | lost with rc 0 | conn 0 | p50 ms | max ms |
|---|---|---|---|---|---|---|---|---|
| before | 704 | 704 | 0 | 0 | 0 | 0 | 4.37 | 8.3 |
| during | 1440 | 1440 | 0 | 677 | 0 | 701 | 30335.04 | 60235.8 |
| after | 2176 | 2176 | 0 | 7 | 0 | 7 | 4.4 | 363.3 |

Disconnect 30.78 s after the cut; reconnect 0.26 s after the restore; first delivery 0.26 s after; backlog flushed 0.39 s after; max latency of messages published during the outage 60.24 s; IMU peak AoI max 60.286 s (at 60.27 s after the cut). DRAIN: acked=4320 of 4320 in 0.05 s. Segment note: None.

Publisher events (s from the cut): SOCKET_OPEN nodelay=1 -29.27; CONNECT rc=Success -29.27; DISCONNECT rc=Keep alive timeout +30.78; DISCONNECT rc=Keep alive timeout +30.78; SOCKET_OPEN nodelay=1 +60.27; CONNECT rc=Success +60.27; DRAIN acked=4320 of 4320 in 0.05 s +150.74; FINISH  +150.74; DISCONNECT rc=Normal disconnection +150.74

Broker 'dropped' lines: 0
Broker client lines: 5
    1795595599 New client connected from 192.168.1.3:36805 as auto-3925FFA4-FF1B-71C7-04BC-79952A10A694 (p2, c1, k30, u'uavpi').
    1795595676 Client auto-3925FFA4-FF1B-71C7-04BC-79952A10A694 has exceeded timeout, disconnecting.
    1795595689 New client connected from 192.168.1.3:59173 as auto-8D9149A8-1A41-0936-96B4-E3D3652E8118 (p2, c1, k30, u'uavpi').
    1795595779 Client auto-8D9149A8-1A41-0936-96B4-E3D3652E8118 disconnected.
    1795595823 Client auto-68BD5D96-8FF8-7009-C21F-E4A2891DC8F8 disconnected.

Throttled in the segment: {'0x0': np.int64(175)}. Chrony after the restore (s, LastRx, last sample): [(5.8382062911987305, 3, '-16us['), (15.868502140045166, 1, '+90us['), (25.8967547416687, 3, '-1262us[-1337us]'), (35.92417812347412, 1, '-1206us[-1253us]'), (45.942482471466064, 3, '+103us['), (55.972686767578125, 1, '+221us['), (66.00073885917664, 3, '-1349us[-1371us]'), (76.03487586975098, 1, '+42us[')]
