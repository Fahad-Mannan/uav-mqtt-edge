#!/usr/bin/env python3
"""Line up the QoS 2 handshake of every message from a packet capture.

The capture (pcapng from dumpcap) holds two interfaces, both filtered to TCP port 1883
with CONNECT segments dropped so the MQTT password is never stored:
  enp0s31f6: Pi <-> broker      A1 PUBLISH, A2 PUBREC, A3 PUBREL, A4 PUBCOMP
  lo:        broker <-> logger  B1 PUBLISH, B2 PUBREC, B3 PUBREL, B4 PUBCOMP
Leg A packets are matched by packet ID on the Pi connection, leg B by packet ID on the
logger connection, and the two legs are joined by (topic, seq) from the JSON payload.
rx.csv adds t_rx_ns. Messages are grouped by position in the burst (by t_pub_ns).

Usage:
  python analysis/pcap_qos2_handshake.py <campaign> [--run qos2_rep1] [--pcap PATH]
Reads  data/<campaign>/capture.pcapng and data/<campaign>/<run>/rx.csv
Writes data/<campaign>/<run>/handshake.csv (one row per message, times in ns, gaps in ms)
"""
import argparse, json, os, socket, struct, sys
from bisect import bisect_left, bisect_right
from collections import Counter
import pandas as pd

M = 0xFFFFFFFF
NAMES = {1: "CONNECT", 2: "CONNACK", 3: "PUBLISH", 4: "PUBACK", 5: "PUBREC", 6: "PUBREL",
         7: "PUBCOMP", 8: "SUBSCRIBE", 9: "SUBACK", 10: "UNSUBSCRIBE", 11: "UNSUBACK",
         12: "PINGREQ", 13: "PINGRESP", 14: "DISCONNECT"}


class ConnectFound(Exception):
    """The capture holds an MQTT CONNECT packet, which carries the password."""


def sdiff(a, b):
    """a - b in TCP sequence-number arithmetic."""
    d = (a - b) & M
    return d - (1 << 32) if d >= 1 << 31 else d


# ---------------------------------------------------------------- pcapng reading
def read_pcapng(path):
    """Yield (interface dict, timestamp ns, frame bytes) for each Enhanced Packet Block."""
    buf = open(path, "rb").read()
    pos, end, ifaces = 0, "<", []
    while pos + 12 <= len(buf):
        if buf[pos:pos + 4] == b"\x0a\x0d\x0d\x0a":              # Section Header Block
            end = "<" if buf[pos + 8:pos + 12] == b"\x4d\x3c\x2b\x1a" else ">"
            ifaces = []
        btype, blen = struct.unpack_from(end + "II", buf, pos)
        if blen < 12:
            raise ValueError(f"corrupt pcapng block at offset {pos}")
        body = buf[pos + 8:pos + blen - 4]
        if btype == 1:                                            # Interface Description
            iface = {"linktype": struct.unpack_from(end + "H", body, 0)[0],
                     "name": f"if{len(ifaces)}", "per_s": 10 ** 6}
            o = 8
            while o + 4 <= len(body):
                code, olen = struct.unpack_from(end + "HH", body, o)
                val = body[o + 4:o + 4 + olen]
                if code == 0:
                    break
                if code == 2:
                    iface["name"] = val.decode(errors="replace").rstrip("\x00")
                elif code == 9:
                    r = val[0]
                    iface["per_s"] = 2 ** (r & 0x7F) if r & 0x80 else 10 ** r
                o += 4 + (olen + 3) // 4 * 4
            ifaces.append(iface)
        elif btype == 6:                                          # Enhanced Packet
            iid, hi, lo, caplen = struct.unpack_from(end + "IIII", body, 0)
            iface = ifaces[iid]
            yield iface, ((hi << 32) | lo) * 10 ** 9 // iface["per_s"], body[20:20 + caplen]
        pos += blen


def parse_tcp(linktype, d):
    """Return (src, sport, dst, dport, seq, ack, flags, payload) for an IPv4/TCP frame."""
    if linktype == 1:                       # Ethernet (also Linux loopback)
        off, et = 14, d[12:14]
        while et == b"\x81\x00":            # 802.1Q tag
            et, off = d[off + 2:off + 4], off + 4
    elif linktype == 113:                   # Linux cooked v1
        off, et = 16, d[14:16]
    elif linktype == 276:                   # Linux cooked v2
        off, et = 20, d[0:2]
    elif linktype in (101, 228):            # raw IPv4
        off, et = 0, b"\x08\x00"
    else:
        return None
    ip = d[off:]
    if et != b"\x08\x00" or len(ip) < 20 or ip[0] >> 4 != 4 or ip[9] != 6:
        return None
    ihl = (ip[0] & 15) * 4
    tot = struct.unpack_from("!H", ip, 2)[0] or len(ip)
    t = ip[ihl:tot]
    sport, dport, seq, ack = struct.unpack_from("!HHII", t, 0)
    return (socket.inet_ntoa(ip[12:16]), sport, socket.inet_ntoa(ip[16:20]), dport,
            seq, ack, t[13], t[(t[12] >> 4) * 4:])


# ---------------------------------------------------------------- TCP -> MQTT
class Stream:
    """One direction of a TCP connection, reassembled into MQTT packets."""

    def __init__(self):
        self.next, self.buf, self.got_data = None, b"", False
        self.gaps = self.retrans = self.start_skip = self.bad = 0

    def feed(self, seq, data):
        """Add a segment; return the MQTT packets it completes as (bytes, end seq)."""
        if self.next is None:
            self.next = seq
        d = sdiff(seq, self.next)
        if d + len(data) <= 0:              # pure retransmission
            self.retrans += 1
            return []
        if d < 0:                           # partial overlap
            data, self.retrans = data[-d:], self.retrans + 1
        elif d > 0:                         # bytes missing (CONNECT dropped, or capture loss)
            if self.got_data:
                self.gaps += 1
            else:
                self.start_skip += 1
            self.buf, self.next = b"", seq
        self.next = (self.next + len(data)) & M
        self.got_data = True
        self.buf += data
        out = []
        while len(self.buf) >= 2:
            rl, i = 0, 1
            for k in range(4):              # remaining-length varint, 1-4 bytes
                if i >= len(self.buf):
                    return out
                b = self.buf[i]
                rl, i = rl + (b & 127) * 128 ** k, i + 1
                if not b & 128:
                    break
            else:
                b = 128
            if self.buf[0] >> 4 == 0 or b & 128:
                self.bad, self.buf = self.bad + 1, b""
                return out
            if len(self.buf) < i + rl:
                break
            pkt, self.buf = self.buf[:i + rl], self.buf[i + rl:]
            out.append((pkt, (self.next - len(self.buf)) & M))
        return out


def mqtt_info(pkt):
    """Decode the fields needed here from one MQTT 3.1.1 packet."""
    ptype, flags = pkt[0] >> 4, pkt[0] & 15
    if ptype == 1:
        raise ConnectFound("capture contains an MQTT CONNECT packet")
    i = 1
    while pkt[i] & 128:
        i += 1
    body = pkt[i + 1:]
    e = {"type": NAMES.get(ptype, str(ptype))}
    if ptype == 3:
        qos = (flags >> 1) & 3
        tl = struct.unpack_from("!H", body, 0)[0]
        j = 2 + tl
        e.update(qos=qos, dup=flags >> 3, topic=body[2:j].decode(errors="replace"), pid=None)
        if qos:
            e["pid"], j = struct.unpack_from("!H", body, j)[0], j + 2
        try:
            js = json.loads(body[j:])
            e.update(seq=js.get("seq"), t_pub_ns=js.get("t_pub_ns"))
        except (ValueError, AttributeError):
            e.update(seq=None, t_pub_ns=None)
    elif ptype in (4, 5, 6, 7) and len(body) >= 2:
        e["pid"] = struct.unpack_from("!H", body, 0)[0]
    return e


def load_connections(pcap, port=1883):
    """Group MQTT packets by (interface, client address) connection."""
    conns, segid = {}, 0
    for iface, ts, frame in read_pcapng(pcap):
        p = parse_tcp(iface["linktype"], frame)
        if p is None:
            continue
        src, sport, dst, dport, seq, ack, flags, payload = p
        if dport == port:
            client, d = (src, sport), "c2s"
        elif sport == port:
            client, d = (dst, dport), "s2c"
        else:
            continue
        key = (iface["name"], client)
        if key not in conns:
            conns[key] = {"iface": iface["name"], "client": f"{client[0]}:{client[1]}",
                          "c2s": Stream(), "s2c": Stream(),
                          "events": [], "c2s_acks": []}
        c = conns[key]
        segid += 1
        if flags & 0x02:                    # SYN
            c[d].next = (seq + 1) & M
            continue
        if d == "c2s" and flags & 0x10:
            c["c2s_acks"].append((ts, ack, len(payload)))
        if payload:
            for pkt, end in c[d].feed(seq, payload):
                e = mqtt_info(pkt)
                e.update(t=ts, dir=d, seg=segid, end=end)
                c["events"].append(e)
    return conns


# ---------------------------------------------------------------- matching
def handshakes(events, pub_dir):
    """Match PUBLISH/PUBREC/PUBREL/PUBCOMP by packet ID; PUBLISH flows in pub_dir."""
    recs, open_ = [], {}
    for e in events:
        typ, pid = e["type"], e.get("pid")
        if typ == "PUBLISH" and e["dir"] == pub_dir and e["qos"] == 2:
            if e["dup"] and pid in open_:
                open_[pid]["n_dup"] += 1
                continue
            r = {"topic": e["topic"], "seq": e["seq"], "t_pub_ns": e["t_pub_ns"],
                 "t1": e["t"], "n_dup": 0}
            open_[pid] = r
            recs.append(r)
        elif pid in open_:
            r = open_[pid]
            if typ == "PUBREC" and e["dir"] != pub_dir and "t2" not in r:
                r["t2"], r["end2"] = e["t"], e["end"]
            elif typ == "PUBREL" and e["dir"] == pub_dir and "t3" not in r:
                r["t3"], r["seg3"] = e["t"], e["seg"]
            elif typ == "PUBCOMP" and e["dir"] != pub_dir:
                r["t4"] = e["t"]
                del open_[pid]
    return recs


def pi_side_context(c, recs):
    """For each Pi message: next Pi PUBLISH after the PUBREC, the Pi's TCP ACK of the
    PUBREC, and whether the PUBREL shared a TCP segment with a PUBLISH."""
    pubs = [e for e in c["events"] if e["dir"] == "c2s" and e["type"] == "PUBLISH"]
    pub_t, pub_segs = [e["t"] for e in pubs], {e["seg"] for e in pubs}
    acks = c["c2s_acks"]
    ack_t = [a[0] for a in acks]
    for r in recs:
        if "t2" in r:
            k = bisect_right(pub_t, r["t2"])
            r["t_next_pub"] = pub_t[k] if k < len(pub_t) else None
            for a in acks[bisect_left(ack_t, r["t2"]):]:
                if a[0] - r["t2"] > 10 ** 9:
                    break
                if sdiff(a[1], r["end2"]) >= 0:
                    r["t_ack2"], r["ack2_bytes"] = a[0], a[2]
                    break
        if "t3" in r:
            r["rel_with_pub"] = r["seg3"] in pub_segs


def analyse(conns, rx=None, burst_gap_ms=20.0):
    """Return (per-message DataFrame, list of per-connection health dicts)."""
    A, B, health = {}, {}, []
    for c in conns.values():
        n = Counter((e["dir"], e["type"]) for e in c["events"])
        pub_dir = "c2s" if n[("c2s", "PUBLISH")] >= n[("s2c", "PUBLISH")] else "s2c"
        recs = handshakes(c["events"], pub_dir)
        if pub_dir == "c2s":
            pi_side_context(c, recs)
        target = A if pub_dir == "c2s" else B
        for r in recs:
            target.setdefault((r["topic"], r["seq"]), r)
        health.append({
            "conn": f"{c['iface']} {c['client']}",
            "role": "publisher" if pub_dir == "c2s" else "subscriber",
            "packets": dict(sorted(Counter(e["type"] for e in c["events"]).items())),
            "unfinished_qos2": sum("t4" not in r for r in recs),
            **{f"{d}_{k}": getattr(c[d], k) for d in ("c2s", "s2c")
               for k in ("gaps", "retrans", "start_skip", "bad")}})
    rx_t = {}
    if rx is not None:
        for row in rx.drop_duplicates(["topic", "seq"]).itertuples():
            rx_t[(row.topic, row.seq)] = row.t_rx_ns
    rows = []
    for key, a in A.items():
        b = B.get(key, {})
        rows.append({
            "topic": key[0], "sensor": key[0].rsplit("/", 1)[-1], "seq": key[1],
            "t_pub_ns": a["t_pub_ns"], "A1": a["t1"], "A2": a.get("t2"), "A3": a.get("t3"),
            "A4": a.get("t4"), "B1": b.get("t1"), "B2": b.get("t2"), "B3": b.get("t3"),
            "B4": b.get("t4"), "t_rx_ns": rx_t.get(key), "t_next_pub": a.get("t_next_pub"),
            "t_ack2": a.get("t_ack2"), "ack2_bytes": a.get("ack2_bytes"),
            "rel_with_pub": a.get("rel_with_pub"), "a_dups": a["n_dup"]})
    df = pd.DataFrame(rows)
    if df.empty:
        return df, health
    tcols = ["t_pub_ns", "A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4", "t_rx_ns",
             "t_next_pub", "t_ack2"]
    for col in tcols:                # exact integer ns; a float64 column would lose ~256 ns
        df[col] = pd.array([r[col] for r in rows], dtype="Int64")
    df = df.sort_values("t_pub_ns").reset_index(drop=True)
    gap = lambda x, y: ((df[x] - df[y]) / 1e6).astype(float)
    df["g0_ms"] = gap("A1", "t_pub_ns")          # Pi publish -> PUBLISH at laptop
    df["a_rec_ms"] = gap("A2", "A1")             # broker sends PUBREC
    df["a_rel_ms"] = gap("A3", "A2")             # round trip through the Pi
    df["a_comp_ms"] = gap("A4", "A3")
    df["fwd_ms"] = gap("B1", "A3")               # broker forwards (negative: before PUBREL)
    df["b_rec_ms"] = gap("B2", "B1")
    df["b_rel_ms"] = gap("B3", "B2")
    df["b_comp_ms"] = gap("B4", "B3")
    df["rx_ms"] = gap("t_rx_ns", "B3")           # logger on_message after PUBREL
    df["lat_ms"] = gap("t_rx_ns", "t_pub_ns")
    df["pi_ack_ms"] = gap("t_ack2", "A2")        # Pi TCP ACK of the PUBREC
    df["rel_minus_next_pub_ms"] = gap("A3", "t_next_pub")
    new = (df["t_pub_ns"].diff() / 1e6).astype(float).fillna(1e9) > burst_gap_ms
    df["burst"] = new.cumsum()
    df["pos"] = df.groupby("burst").cumcount() + 1
    df["size"] = df.groupby("burst")["pos"].transform("max")
    df["group"] = [f"{s} lone" if n == 1 else f"{s} {p}/{n}"
                   for s, p, n in zip(df["sensor"], df["pos"], df["size"])]
    return df, health


GAPS = ["g0_ms", "a_rec_ms", "a_rel_ms", "a_comp_ms", "fwd_ms", "b_rec_ms", "b_rel_ms",
        "b_comp_ms", "rx_ms", "lat_ms", "pi_ack_ms", "rel_minus_next_pub_ms"]


def report(df, health):
    print("Connections:")
    for h in health:
        print(" ", h)
    if df.empty:
        print("No QoS 2 messages found.")
        return
    print(f"\n{len(df)} messages, {df['burst'].nunique()} bursts/singles. Gaps in ms.")
    for g, sub in df.groupby("group", sort=True):
        q = sub[GAPS].quantile([0.5, 0.95, 0.99]).T
        q.columns = ["p50", "p95", "p99"]
        q["max"] = sub[GAPS].max()
        q["n"] = sub[GAPS].notna().sum()
        rel = sub["rel_with_pub"].dropna().astype(bool)
        acked = sub["ack2_bytes"].dropna()
        print(f"\n== {g}  (n={len(sub)})  lat>20ms: {(sub['lat_ms'] > 20).mean():.0%}  "
              f"a_rel>20ms: {(sub['a_rel_ms'] > 20).mean():.0%}  "
              f"PUBREL in same segment as a PUBLISH: {rel.mean() if len(rel) else float('nan'):.0%}  "
              f"PUBREC ACKed by pure ACK: {(acked == 0).mean() if len(acked) else float('nan'):.0%}")
        print(q.round(3).to_string())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("campaign")
    p.add_argument("--run", default="qos2_rep1")
    p.add_argument("--pcap", default=None, help="default data/<campaign>/capture.pcapng")
    p.add_argument("--burst-gap-ms", type=float, default=20.0)
    a = p.parse_args()
    base = os.path.expanduser(f"~/uav-mqtt/data/{a.campaign}")
    pcap = a.pcap or os.path.join(base, "capture.pcapng")
    rdir = os.path.join(base, a.run)
    try:
        conns = load_connections(pcap)
    except ConnectFound:
        sys.exit(f"{pcap} contains an MQTT CONNECT packet, which holds the password. "
                 "Delete the file and check the capture filter.")
    rx_path = os.path.join(rdir, "rx.csv")
    rx = pd.read_csv(rx_path) if os.path.exists(rx_path) else None
    df, health = analyse(conns, rx, a.burst_gap_ms)
    report(df, health)
    if not df.empty and os.path.isdir(rdir):
        df.to_csv(os.path.join(rdir, "handshake.csv"), index=False)
        print(f"\nWrote {os.path.join(rdir, 'handshake.csv')}")


if __name__ == "__main__":
    main()
