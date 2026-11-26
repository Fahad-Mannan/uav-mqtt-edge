#!/usr/bin/env python3
"""Analyse a flight by the drone's actual position instead of the timetable segments.

Reads the Pixhawk DataFlash log (.bin) with pymavlink:
  - log time (TimeUS) -> UTC from GPS week/ms (linear fit; UTC = GPS - leap seconds);
  - home = the last ORGN Type 1 (set at the last arming);
  - POS (EKF position) -> horizontal distance from home and altitude above home (POS.Alt - home Alt).
Every message the Pi sent (pi_segments/*/pi_log.csv) gets distance and altitude at its t_pub,
and is put in a position bin: ground (alt < 1 m), hover_<A> (alt > 14 m, distance A +- 2 m),
hover_<B> (distance B +- 2 m), transit (everything else). Per bin and QoS: messages sent and
received, PDR, latency p50/p95/p99/max, % > 20 ms, RSSI (station dump), scans (iw event).
Optionally the same table for a reference flight folder (no position: one bin "ref").

Clock check: the Pi's BMP280 pressure (Pi clock, chrony-synced to the laptop) is cross-correlated
with the Pixhawk BARO pressure (GPS time) to estimate the laptop/Pi clock offset from GPS time.

--origin 'LAT,LON' or 'home:<other.bin>' measures distance from that point (e.g. the router) instead
of home; altitude stays above this flight's home. msgs_pos.csv then has distance from the origin.

Usage: python analysis/flight_position.py data/<session>/<flight> <log.bin> [--ref data/<session>/ref1]
       [--hovers 28,100 | --hovers auto] [--origin home:<log.bin>] [--leap 18]
Writes <flight>/position/{msgs_pos.csv, track.csv, by_position.csv, by_position.md}.
"""
import argparse, glob, json, math, os, re, sys
import numpy as np
import pandas as pd

p = argparse.ArgumentParser()
p.add_argument("flight")
p.add_argument("bin")
p.add_argument("--ref", default=None)
p.add_argument("--hovers", default="28,100",
               help="hover distances, m (bin = +- --hover-tol); 'auto' = the hovers flight_state.py detects in the "
                    "track (speed < 1 m/s for >= 20 s, altitude above --hover-min-alt)")
p.add_argument("--hover-tol", type=float, default=2.0)
p.add_argument("--hover-min-alt", type=float, default=14.0)
p.add_argument("--ground-alt", type=float, default=1.0)
p.add_argument("--leap", type=int, default=18, help="GPS - UTC leap seconds")
p.add_argument("--clock-shift", type=float, default=0.0,
               help="add to Pi/laptop times before looking up the position (sensitivity check), s")
p.add_argument("--origin", default=None,
               help="measure horizontal distance from this point instead of home (e.g. the router): 'LAT,LON' "
                    "(degrees) or 'home:<other log.bin>' (that log's last ORGN Type 1). Altitude stays relative "
                    "to this flight's own home (ground at takeoff)")
a = p.parse_args()
HOVERS = None if a.hovers == "auto" else [float(x) for x in a.hovers.split(",")]
GPS_EPOCH_UNIX = 315964800          # 1980-01-06 00:00:00 UTC
out = os.path.join(a.flight, "position" + (f"_shift{a.clock_shift:+g}" if a.clock_shift else ""))
os.makedirs(out, exist_ok=True)


# ---------------------------------------------------------------- Pixhawk log
def read_bin(path):
    from pymavlink import mavutil
    m = mavutil.mavlink_connection(path)
    gps, pos, orgn, baro, mode, arm = [], [], [], [], [], []
    while True:
        x = m.recv_match(type=["GPS", "POS", "ORGN", "BARO", "MODE", "ARM"])
        if x is None:
            break
        t = x.get_type()
        if t == "GPS" and x.I == 0 and x.Status >= 3 and x.GWk > 0:
            gps.append((x.TimeUS, x.GWk, x.GMS, x.Status, x.NSats, x.HDop))
        elif t == "POS":
            pos.append((x.TimeUS, x.Lat, x.Lng, x.Alt))
        elif t == "ORGN":
            orgn.append((x.TimeUS, x.Type, x.Lat, x.Lng, x.Alt))
        elif t == "BARO" and x.I == 0:
            baro.append((x.TimeUS, x.Press, x.Alt))
        elif t == "MODE":
            mode.append((x.TimeUS, x.ModeNum))
        elif t == "ARM":
            arm.append((x.TimeUS, x.ArmState))
    cols = lambda *c: list(c)
    return (pd.DataFrame(gps, columns=cols("TimeUS", "GWk", "GMS", "Status", "NSats", "HDop")),
            pd.DataFrame(pos, columns=cols("TimeUS", "Lat", "Lng", "Alt")),
            pd.DataFrame(orgn, columns=cols("TimeUS", "Type", "Lat", "Lng", "Alt")),
            pd.DataFrame(baro, columns=cols("TimeUS", "Press", "Alt")),
            pd.DataFrame(mode, columns=cols("TimeUS", "ModeNum")),
            pd.DataFrame(arm, columns=cols("TimeUS", "ArmState")))


gps, pos, orgn, baro, mode, arm = read_bin(a.bin)
gps["utc"] = GPS_EPOCH_UNIX + gps.GWk * 604800 + gps.GMS / 1e3 - a.leap
b, c0 = np.polyfit(gps.TimeUS / 1e6, gps.utc, 1)
resid = gps.utc - (c0 + b * gps.TimeUS / 1e6)
to_utc = lambda us: c0 + b * np.asarray(us) / 1e6
clock = {"gps_fixes": len(gps), "slope_ppm": (b - 1) * 1e6, "resid_ms_p50": float(resid.abs().median() * 1e3),
         "resid_ms_max": float(resid.abs().max() * 1e3)}

home = orgn[orgn.Type == 1].iloc[-1]
R = 6371008.8


def parse_origin(spec):
    """--origin -> (lat, lon, description), or None for home."""
    if spec is None:
        return None
    if spec.startswith("home:"):
        o = read_bin(spec[5:])[2]
        o = o[o.Type == 1]
        if not len(o):
            sys.exit(f"--origin {spec}: no ORGN Type 1 in that log")
        o = o.iloc[-1]
        return float(o.Lat), float(o.Lng), f"home of {os.path.basename(spec[5:])}"
    lat, lon = (float(x) for x in spec.split(","))
    return lat, lon, "given"


ORIGIN = parse_origin(a.origin)
# distances are measured from `ref_pt` (home, or --origin); altitude is always above this flight's home
ref_pt = home.copy()
if ORIGIN:
    ref_pt["Lat"], ref_pt["Lng"] = ORIGIN[0], ORIGIN[1]
    _n = math.radians(home.Lat - ORIGIN[0]) * R
    _e = math.radians(home.Lng - ORIGIN[1]) * R * math.cos(math.radians(ORIGIN[0]))
    ORIGIN_NOTE = (f"Distance origin: {ORIGIN[2]} ({ORIGIN[0]:.7f}, {ORIGIN[1]:.7f}); this flight's home is "
                   f"{math.hypot(_n, _e):.1f} m from it at bearing {math.degrees(math.atan2(_e, _n)) % 360:.0f} deg.")
    print(ORIGIN_NOTE)
else:
    ORIGIN_NOTE = "Distance origin: home."
pos["utc"] = to_utc(pos.TimeUS)
pos["north_m"] = np.radians(pos.Lat - ref_pt.Lat) * R
pos["east_m"] = np.radians(pos.Lng - ref_pt.Lng) * R * math.cos(math.radians(ref_pt.Lat))
pos["dist_m"] = np.hypot(pos.north_m, pos.east_m)
pos["bearing_deg"] = np.degrees(np.arctan2(pos.east_m, pos.north_m)) % 360
pos["alt_m"] = pos.Alt - home.Alt
arm["utc"] = to_utc(arm.TimeUS)
mode["utc"] = to_utc(mode.TimeUS)
pos.to_csv(os.path.join(out, "track.csv"), index=False)
if HOVERS is None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import flight_state
    _tr = flight_state.track(pos, ref_pt)     # distance from the origin, altitude above home
    _arm_u, _dis_u = arm[arm.ArmState == 1].utc, arm[arm.ArmState == 0].utc
    # first arming (or log start) to last disarm (or log end): nothing after a crash-disarm counts
    _hv = flight_state.detect_hovers(_tr, min_alt=a.hover_min_alt, tol=a.hover_tol,
                                     t0=_arm_u.min() if len(_arm_u) else _tr.utc.min(),
                                     t1=_dis_u.max() if len(_dis_u) else _tr.utc.max())
    HOVERS = [h["dist_m"] for h in _hv]
    if not HOVERS:
        sys.exit("--hovers auto: no hover detected in the track")
    print("hovers detected (flight_state.detect_hovers): " + ", ".join(f"{h['dist_m']:g} m" for h in _hv))


# after the log ends (logging stops at disarm) the drone is on the ground: hold the last position
# if the last logged altitude is below the ground threshold
_landed = pos.alt_m.iloc[-1] < a.ground_alt


def at(t_unix, col):
    t = np.asarray(t_unix) + a.clock_shift
    return np.interp(t, pos.utc, pos[col], left=np.nan, right=pos[col].iloc[-1] if _landed else np.nan)


# ---------------------------------------------------------------- messages
def load(flight):
    sent = []
    for f in sorted(glob.glob(os.path.join(flight, "pi_segments", "*", "pi_log.csv"))):
        d = pd.read_csv(f, usecols=["topic", "seq", "t_sample_ns", "t_pub_ns", "qos", "bytes", "payload"])
        d["segment"] = os.path.basename(os.path.dirname(f))
        sent.append(d)
    sent = pd.concat(sent, ignore_index=True)
    rx = pd.read_csv(os.path.join(flight, "rx_all.csv"))
    rx = rx.drop_duplicates(["topic", "t_pub_ns"])
    m = sent.merge(rx[["topic", "t_pub_ns", "t_rx_ns", "latency_ms", "dup"]], on=["topic", "t_pub_ns"], how="left")
    m["rcvd"] = m.latency_ms.notna()
    m["t_pub"] = m.t_pub_ns / 1e9
    m["sensor"] = m.topic.str.split("/").str[-1]
    return m


def side(flight):
    """station dump RSSI samples (t, dBm) and iw event scans (start, end)."""
    rssi, t = [], None
    sd = os.path.join(flight, "pi_side", "station_dump.log")
    if os.path.exists(sd):
        for line in open(sd):
            if line.startswith("T "):
                t = float(line.split()[1])
            else:
                mm = re.match(r"\s*signal:\s*(-?\d+)", line)
                if mm and t is not None:
                    rssi.append((t, int(mm.group(1))))
    rssi = pd.DataFrame(rssi, columns=["t", "dbm"])
    scans, st = [], None
    ie = os.path.join(flight, "pi_side", "iw_event.log")
    if os.path.exists(ie):
        for line in open(ie):
            mm = re.match(r"([\d.]+): .*scan (started|finished|aborted)", line)
            if mm:
                if mm.group(2) == "started":
                    st = float(mm.group(1))
                elif st is not None:
                    scans.append((st, float(mm.group(1))))
                    st = None
    return rssi, pd.DataFrame(scans, columns=["start", "end"])


def seg_windows(flight):
    s = pd.read_csv(os.path.join(flight, "segments.csv"))
    return s[["label", "qos", "actual_start_unix", "end_unix"]]


def qos_at(t, segs):
    q = np.full(len(t), -1)
    for _, s in segs.iterrows():
        q[(t >= s.actual_start_unix) & (t <= s.end_unix)] = s.qos
    return q


def pbin(dist, alt):
    lab = np.full(len(dist), "transit", dtype=object)
    lab[np.isnan(dist)] = "no_position"
    for h in sorted(HOVERS, reverse=True):
        sel = (np.abs(dist - h) <= a.hover_tol) & (alt > a.hover_min_alt)
        lab[sel] = f"hover_{h:g}m"
    lab[alt < a.ground_alt] = "ground"
    return lab


def table(m, rssi, scans, segs, binner):
    m = m.copy()
    m["bin"] = binner(m.t_pub.values)
    rssi = rssi.copy()
    rssi["bin"] = binner(rssi.t.values)
    rssi["qos"] = qos_at(rssi.t.values, segs)
    rows = []
    for (bn, q), g in m.groupby(["bin", "qos"]):
        L = g.latency_ms.dropna()
        r = rssi[(rssi.bin == bn) & (rssi.qos == q)].dbm
        # scans overlapping this bin x QoS: any sent message of the group published inside the scan
        ts = g.t_pub.values
        sc = [s for _, s in scans.iterrows() if ((ts >= s.start) & (ts <= s.end)).any()]
        in_scan = np.zeros(len(g), bool)
        for _, s in scans.iterrows():
            in_scan |= (ts >= s.start - 1) & (ts <= s.end + 1)
        Ln = g.latency_ms[~in_scan].dropna()
        rows.append({"bin": bn, "qos": q, "sent": len(g), "rcvd": int(g.rcvd.sum()),
                     "pdr_pct": 100 * g.rcvd.mean(), "time_s": len(g) / 24.0,
                     "dist_m_mean": g.get("dist_m", pd.Series(dtype=float)).mean(),
                     "alt_m_mean": g.get("alt_m", pd.Series(dtype=float)).mean(),
                     "p50": L.quantile(.5), "p95": L.quantile(.95), "p99": L.quantile(.99), "max": L.max(),
                     "gt20_pct": 100 * (L > 20).mean(), "n_noscan": len(Ln),
                     "noscan_p95": Ln.quantile(.95) if len(Ln) else np.nan,
                     "noscan_gt20_pct": 100 * (Ln > 20).mean() if len(Ln) else np.nan,
                     "rssi_mean": r.mean(), "rssi_min": r.min(), "rssi_n": len(r),
                     "scans": len(sc), "msgs_in_scan_pm1s": int(in_scan.sum())})
    return pd.DataFrame(rows)


m = load(a.flight)
m["dist_m"] = at(m.t_pub.values, "dist_m")
m["alt_m"] = at(m.t_pub.values, "alt_m")
segs = seg_windows(a.flight)
rssi, scans = side(a.flight)
binner = lambda t: pbin(at(t, "dist_m"), at(t, "alt_m"))
m["bin"] = binner(m.t_pub.values)          # saved in msgs_pos.csv (used by link_bands.py)
T = table(m, rssi, scans, segs, binner)
order = {"ground": 0, **{f"hover_{h:g}m": i + 1 for i, h in enumerate(HOVERS)}, "transit": 9, "no_position": 10}
T = T.sort_values(["bin", "qos"], key=lambda s: s.map(order) if s.name == "bin" else s)
T.insert(0, "flight", os.path.basename(a.flight.rstrip("/")))
if a.ref:
    mr = load(a.ref)
    rr, sr = side(a.ref)
    Tr = table(mr, rr, sr, seg_windows(a.ref), lambda t: np.full(len(t), "ref", dtype=object))
    Tr.insert(0, "flight", os.path.basename(a.ref.rstrip("/")))
    T = pd.concat([T, Tr], ignore_index=True)
T.to_csv(os.path.join(out, "by_position.csv"), index=False)
m.drop(columns=["payload"]).to_csv(os.path.join(out, "msgs_pos.csv"), index=False)

# ---------------------------------------------------------------- clock check: BMP280 vs BARO
bmp = m[m.sensor == "bmp280"].copy()
bmp["press_pa"] = bmp.payload.str.extract(r'"pressure_hpa": ([\d.]+)').astype(float) * 100
bmp["t"] = bmp.t_sample_ns / 1e9
bu = to_utc(baro.TimeUS)
lags = np.arange(-5, 5.0001, 0.01)
cc = []
for L in lags:   # Pi time + L = GPS time
    ref = np.interp(bmp.t + L, bu, baro.Press, left=np.nan, right=np.nan)
    ok = ~np.isnan(ref)
    x, y = bmp.press_pa[ok] - bmp.press_pa[ok].mean(), ref[ok] - ref[ok].mean()
    cc.append(float((x * y).sum() / np.sqrt((x * x).sum() * (y * y).sum())))
cc = np.array(cc)
best = lags[cc.argmax()]
# width: lags where the correlation is within 0.001 of the peak
near = lags[cc >= cc.max() - 0.001]
clock.update(bmp_vs_baro_lag_s=float(best), corr=float(cc.max()), lag_range_s=[float(near.min()), float(near.max())],
             press_range_pa=float(bmp.press_pa.max() - bmp.press_pa.min()))

# ---------------------------------------------------------------- report
arms = arm[arm.ArmState == 1].utc.values
disarms = arm[arm.ArmState == 0].utc.values
ts = lambda u: pd.Timestamp(u, unit="s", tz="UTC").tz_convert("America/Denver").strftime("%H:%M:%S.%f")[:-4]
air = pos[(pos.utc >= m.t_pub.min() - 120) & (pos.utc <= m.t_pub.max() + 120)]
lines = [f"# {os.path.basename(a.flight.rstrip('/'))} by position", "",
         f"Log `{os.path.basename(a.bin)}`. GPS -> UTC fit over {clock['gps_fixes']} fixes: slope "
         f"{clock['slope_ppm']:+.1f} ppm, |residual| p50 {clock['resid_ms_p50']:.1f} ms, max {clock['resid_ms_max']:.1f} ms "
         f"(leap {a.leap} s). Home (last ORGN Type 1, at {ts(to_utc(home.TimeUS))} MST): "
         f"{home.Lat:.7f}, {home.Lng:.7f}, {home.Alt:.2f} m. {ORIGIN_NOTE} Hover distances "
         f"{', '.join(f'{h:g}' for h in HOVERS)} m ({'detected from the track' if a.hovers == 'auto' else 'given'}), "
         f"+-{a.hover_tol:g} m, altitude > {a.hover_min_alt:g} m.",
         f"Arm {', '.join(ts(x) for x in arms)}; disarm {', '.join(ts(x) for x in disarms)} (MST).",
         f"Clock: Pi BMP280 vs Pixhawk BARO best lag {best:+.2f} s (Pi + lag = GPS; correlation {cc.max():.4f}, "
         f"within 0.001 of peak over {near.min():+.2f}..{near.max():+.2f} s; pressure range "
         f"{clock['press_range_pa']:.0f} Pa).", ""]
cols = ["flight", "bin", "qos", "sent", "rcvd", "pdr_pct", "time_s", "dist_m_mean", "alt_m_mean", "p50", "p95", "p99",
        "max", "gt20_pct", "noscan_p95", "noscan_gt20_pct", "rssi_mean", "rssi_min", "scans", "msgs_in_scan_pm1s"]
def md(df):
    f = lambda v: f"{v:.2f}" if isinstance(v, (float, np.floating)) else str(v)
    return "\n".join(["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
                     + ["| " + " | ".join(f(v) for v in r) + " |" for r in df.itertuples(index=False)])
lines.append(md(T[cols]))
open(os.path.join(out, "by_position.md"), "w").write("\n".join(lines) + "\n")
json.dump(clock, open(os.path.join(out, "clock.json"), "w"), indent=1)
print("\n".join(lines))
