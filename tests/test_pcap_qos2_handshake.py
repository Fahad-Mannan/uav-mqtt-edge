#!/usr/bin/env python3
"""Short check of analysis/pcap_qos2_handshake.py on a synthetic pcapng.

Scenario: one 2 Hz burst (bmp280, mpu6050, ina219) at QoS 2. The ina219 PUBREL is held
until it rides in the same TCP segment as the next IMU PUBLISH, 49 ms after its PUBREC.
The CONNECT is missing (as the capture filter drops it), one segment is retransmitted,
and the loopback interface uses microsecond timestamps while enp0s31f6 uses ns.
Run: python tests/test_pcap_qos2_handshake.py
"""
import json, os, socket, struct, sys, tempfile
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "analysis"))
import pcap_qos2_handshake as h

T0 = 1_763_000_000_000_000_000          # wall-clock ns
ms = lambda x: T0 + int(round(x * 1e6))


def pub(topic, pid, seq, t_pub_ms):
    body = json.dumps({"seq": seq, "t_pub_ns": ms(t_pub_ms)}).encode()
    var = struct.pack("!H", len(topic)) + topic.encode() + struct.pack("!H", pid) + body
    return bytes([0x34, len(var)]) + var          # PUBLISH, QoS 2 (payload < 128 bytes)


def ack(kind, pid):
    code = {"PUBREC": 0x50, "PUBREL": 0x62, "PUBCOMP": 0x70}[kind]
    return bytes([code, 2]) + struct.pack("!H", pid)


class Conn:
    def __init__(self, iface, ip, port, frames):
        self.iface, self.ip, self.port, self.frames = iface, ip, port, frames
        self.seq = {"c2s": 1000, "s2c": 5000}

    def seg(self, t, d, data=b"", flags=0x18, seq=None):
        other = "s2c" if d == "c2s" else "c2s"
        s = self.seq[d] if seq is None else seq
        src, sp, dst, dp = ((self.ip, self.port, "192.168.1.4", 1883) if d == "c2s"
                            else ("192.168.1.4", 1883, self.ip, self.port))
        tcp = struct.pack("!HHIIBBHHH", sp, dp, s, self.seq[other], 5 << 4, flags, 65535, 0, 0)
        ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 40 + len(data), 0, 0, 64, 6, 0,
                         socket.inet_aton(src), socket.inet_aton(dst))
        self.frames.append((ms(t), self.iface, b"\0" * 12 + b"\x08\x00" + ip + tcp + data))
        if seq is None:
            self.seq[d] = (s + len(data) + (1 if flags & 0x02 else 0)) & 0xFFFFFFFF


def write_pcapng(path, frames):
    out = struct.pack("<IIIHHqI", 0x0A0D0D0A, 28, 0x1A2B3C4D, 1, 0, -1, 28)
    for name, res in (("enp0s31f6", 9), ("lo", 6)):
        opts = struct.pack("<HHB3x", 9, 1, res)
        n = name.encode()
        opts += struct.pack("<HH", 2, len(n)) + n + b"\0" * (-len(n) % 4) + b"\0" * 4
        blen = 20 + len(opts)
        out += struct.pack("<IIHHI", 1, blen, 1, 0, 262144) + opts + struct.pack("<I", blen)
    for t, iid, d in sorted(frames, key=lambda f: f[0]):
        per_s = 10 ** 9 if iid == 0 else 10 ** 6
        ticks = t * per_s // 10 ** 9
        pad = b"\0" * (-len(d) % 4)
        blen = 32 + len(d) + len(pad)
        out += struct.pack("<IIIIIII", 6, blen, iid, ticks >> 32, ticks & 0xFFFFFFFF,
                           len(d), len(d)) + d + pad + struct.pack("<I", blen)
    open(path, "wb").write(out)


def scenario(path):
    frames, rx = [], []
    pi, lg = Conn(0, "192.168.1.3", 40000, frames), Conn(1, "192.168.1.4", 50000, frames)
    pi.seg(0, "c2s", flags=0x02)
    pi.seq["c2s"] += 30                              # CONNECT dropped by the capture filter
    pi.seg(1, "s2c", b"\x20\x02\x00\x00")            # CONNACK
    T = lambda s: f"uav/uav_01/{s}"
    bmp_seg_seq = pi.seq["c2s"]
    pi.seg(103, "c2s", pub(T("bmp280"), 1, 0, 100))
    pi.seg(104, "s2c", ack("PUBREC", 1))
    pi.seg(105, "c2s", pub(T("mpu6050"), 2, 0, 102))
    pi.seg(106, "s2c", ack("PUBREC", 2))
    pi.seg(107, "c2s", pub(T("ina219"), 3, 0, 104))
    pi.seg(108, "c2s", ack("PUBREL", 1))
    pi.seg(108.2, "s2c", ack("PUBREC", 3) + ack("PUBCOMP", 1))
    pi.seg(110, "c2s", ack("PUBREL", 2))
    pi.seg(111, "c2s", flags=0x10)                   # pure ACK of the ina219 PUBREC
    pi.seg(111.5, "s2c", ack("PUBCOMP", 2))
    pi.seg(120, "c2s", pub(T("bmp280"), 1, 0, 100), seq=bmp_seg_seq)   # retransmission
    pi.seg(157.2, "c2s", pub(T("mpu6050"), 4, 1, 152) + ack("PUBREL", 3))
    pi.seg(158, "s2c", ack("PUBREC", 4) + ack("PUBCOMP", 3))
    pi.seg(161, "c2s", ack("PUBREL", 4))
    pi.seg(162, "s2c", ack("PUBCOMP", 4))
    # Logger leg: mosquitto forwards on PUBREL; its own packet IDs
    for bpid, (s, seq, a3) in enumerate([("bmp280", 0, 108), ("mpu6050", 0, 110),
                                         ("ina219", 0, 157.2), ("mpu6050", 1, 161)], 1):
        tp = {"bmp280": 100, "mpu6050": 102 if seq == 0 else 152, "ina219": 104}[s]
        lg.seg(a3 + 0.1, "s2c", pub(T(s), bpid, seq, tp))
        lg.seg(a3 + 0.3, "c2s", ack("PUBREC", bpid))
        lg.seg(a3 + 0.4, "s2c", ack("PUBREL", bpid))
        lg.seg(a3 + 0.6, "c2s", ack("PUBCOMP", bpid))
        rx.append({"t_rx_ns": ms(a3 + 0.7), "topic": T(s), "seq": seq})
    write_pcapng(path, frames)
    return pd.DataFrame(rx)


with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "synthetic.pcapng")
    rx = scenario(path)
    conns = h.load_connections(path)
    df, health = h.analyse(conns, rx)
    h.report(df, health)
    pi_h = next(x for x in health if x["role"] == "publisher")
    assert len(df) == 4 and df["B3"].notna().all() and df["A4"].notna().all()
    assert pi_h["c2s_start_skip"] == 1 and pi_h["c2s_retrans"] == 1 and pi_h["c2s_gaps"] == 0
    ina = df[df.sensor == "ina219"].iloc[0]
    assert ina["group"] == "ina219 3/3" and bool(ina["rel_with_pub"])
    # PUBREC (108.2) is ACKed by the Pi's next data segment (PUBREL 2 at 110)
    assert abs(ina["a_rel_ms"] - 49.0) < 1e-6 and abs(ina["pi_ack_ms"] - 1.8) < 1e-6
    assert ina["ack2_bytes"] == 4 and abs(ina["rel_minus_next_pub_ms"]) < 1e-6
    assert abs(ina["lat_ms"] - 53.9) < 1e-3 and abs(ina["rx_ms"] - 0.3) < 1e-3
    bmp = df[df.sensor == "bmp280"].iloc[0]
    assert bmp["group"] == "bmp280 1/3" and abs(bmp["a_rel_ms"] - 4.0) < 1e-6
    assert not bmp["rel_with_pub"] and abs(bmp["fwd_ms"] - 0.1) < 1e-3
    assert df.iloc[-1]["group"] == "mpu6050 lone"

    # A capture that still contains a CONNECT must be refused
    frames = []
    c = Conn(0, "192.168.1.3", 40001, frames)
    c.seg(0, "c2s", flags=0x02)
    c.seg(1, "c2s", bytes([0x10, 4]) + b"\0\0\0\0")
    write_pcapng(path, frames)
    try:
        h.load_connections(path)
        raise AssertionError("CONNECT not detected")
    except h.ConnectFound:
        pass
print("\nPASS")
