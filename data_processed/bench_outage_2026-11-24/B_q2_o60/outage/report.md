# Outage run B_q2_o60 (QoS 2, outage 60.01 s at +30.03 s)

Broker limits {'max_queued_messages': 'default', 'max_inflight_messages': 'default'}. Ping during cut answered: False; after: True; qdisc clean after: True.

Sent 4320, received unique 2856, lost 1464, duplicate rows 0 (dup flag 0).

| phase | sent | rcvd | lost | rc 4 | lost with rc 0 | conn 0 | p50 ms | max ms |
|---|---|---|---|---|---|---|---|---|
| before | 703 | 703 | 0 | 0 | 0 | 0 | 5.14 | 12.9 |
| during | 1440 | 20 | 1420 | 676 | 744 | 700 | 61569.17 | 61941.9 |
| after | 2177 | 2133 | 44 | 44 | 0 | 44 | 5.28 | 296.2 |

Disconnect 30.8 s after the cut; reconnect 1.78 s after the restore; first delivery 1.94 s after; backlog flushed 1.95 s after; max latency of messages published during the outage 61.94 s; IMU peak AoI max 61.992 s (at 61.96 s after the cut). DRAIN: acked=4320 of 4320 in 0.05 s. Segment note: None.

Publisher events (s from the cut): SOCKET_OPEN nodelay=1 -29.24; CONNECT rc=Success -29.24; DISCONNECT rc=Keep alive timeout +30.80; DISCONNECT rc=Keep alive timeout +30.80; SOCKET_OPEN nodelay=1 +61.79; CONNECT rc=Success +61.80; DRAIN acked=4320 of 4320 in 0.05 s +150.77; FINISH  +150.77; DISCONNECT rc=Normal disconnection +150.77

Broker 'dropped' lines: 0
Broker client lines: 5
    1795596159 New client connected from 192.168.1.3:46195 as auto-361308BF-05DC-5E0C-7CBF-56CB4BD6AAA4 (p2, c1, k30, u'uavpi').
    1795596234 Client auto-361308BF-05DC-5E0C-7CBF-56CB4BD6AAA4 has exceeded timeout, disconnecting.
    1795596250 New client connected from 192.168.1.3:36307 as auto-193CBF12-E770-191C-C0ED-B959E030786F (p2, c1, k30, u'uavpi').
    1795596339 Client auto-193CBF12-E770-191C-C0ED-B959E030786F disconnected.
    1795596383 Client auto-E49CD199-EC70-96FB-F0D4-DC928006529D disconnected.

Throttled in the segment: {'0x0': np.int64(175)}. Chrony after the restore (s, LastRx, last sample): [(5.811725616455078, 1, '-74us['), (15.829754114151001, 3, '-19us[+3889ns]'), (25.86189317703247, 9, '-577us['), (35.89212989807129, 3, '-41us['), (45.92324876785278, 1, '-171us['), (55.96038889884949, 3, '-143us['), (65.98858666419983, 5, '-34us['), (76.02313089370728, 3, '-170us[')]
