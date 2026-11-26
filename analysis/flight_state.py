#!/usr/bin/env python3
"""Flight state from a Pixhawk DataFlash log (.bin): hovers, wind proxy, battery, throttle, vibration, events.

For each armed interval in the log (a "flight"):
  - track: horizontal distance from home (last ORGN Type 1 before or at that arming; else the last
    one in the log) and altitude above home, from POS; log time -> UTC from GPS week/ms (linear fit);
  - hovers detected from the track: runs of at least --min-hover-s where the horizontal speed
    (1 s smoothing) stays below --max-speed, altitude above --min-alt and distance above --min-dist.
    Runs whose median distances are within 5 m and less than 15 s apart are merged. Each hover is
    reported by its median distance and its window: the longest contiguous stretch within
    +-hover_tol (2 m) of that distance with altitude above --min-alt (the same window
    flight_position.py uses for a hover bin);
  - per hover: altitude, lean angle (ATT roll/pitch/yaw -> tilt of the thrust vector), direction the
    thrust leans toward (= wind from, hypothesis: no drag calibration, so no m/s; EKF3 wind states
    are zero without drag fusion or airspeed), throttle ThO/ThH (CTUN), current (BAT), VIBE;
  - per flight: battery V at arm / min / at disarm / 10 s after, mAh and Wh used, mean current
    airborne, hover throttle (ThH at arm and disarm, MOT_THST_HOVER first/last logged), VIBE mean/p95/max per
    axis airborne, clip increase, max distance and altitude, disarm position;
  - events: MODE changes, MSG (boot banner lines dropped), ERR, EV, ARM.

--hovers 50,150 compares the detected hover distances with the planned ones and warns when a
planned hover has no detected hover within 2 m (--warn-m).

Usage: python analysis/flight_state.py <log.bin> [--hovers 50,150] [--out DIR]
Writes DIR/flight_state.csv (one row per flight and per hover, column `kind`) and
DIR/flight_state.txt (summary + events). Default DIR: <log dir>/<log stem>_state/.
Also importable: load_log(), track(), detect_hovers() (used by flight_position.py --hovers auto).
"""
import argparse, math, os, sys
import numpy as np
import pandas as pd

GPS_EPOCH_UNIX = 315964800          # 1980-01-06 00:00:00 UTC
R_EARTH = 6371008.8
TYPES = ["GPS", "POS", "ORGN", "ATT", "CTUN", "BAT", "VIBE", "XKF2", "MODE", "MSG", "ERR", "EV", "ARM", "PARM"]
MODES = {0: "Stabilize", 1: "Acro", 2: "AltHold", 3: "Auto", 4: "Guided", 5: "Loiter", 6: "RTL", 7: "Circle",
         9: "Land", 16: "PosHold", 17: "Brake", 21: "SmartRTL"}
EVENTS = {10: "ARMED", 11: "DISARMED", 15: "AUTO_ARMED", 17: "LAND_COMPLETE_MAYBE", 18: "LAND_COMPLETE",
          19: "LOST_GPS", 25: "SET_HOME", 28: "NOT_LANDED", 56: "MOTORS_INTERLOCK_DISABLED",
          57: "MOTORS_INTERLOCK_ENABLED", 62: "EKF_YAW_RESET"}
BANNER = ("ArduCopter", "ChibiOS", "Pixhawk", "Param space", "RC Protocol", "RCOut", "New mission", "New rally",
          "New fence", "Frame:", "probing", "u-blox")


def load_log(path, leap=18):
    """All messages of TYPES (first instance only for GPS/BAT, core 0 for XKF2, IMU 0 for VIBE) as
    DataFrames with a `utc` column, plus the GPS fit."""
    from pymavlink import mavutil
    m = mavutil.mavlink_connection(path)
    rows, cols = {t: [] for t in TYPES}, {}
    while True:
        x = m.recv_match(type=TYPES)
        if x is None:
            break
        t = x.get_type()
        if (t in ("GPS", "BAT") and getattr(x, "I" if t == "GPS" else "Inst", 0) != 0) or \
           (t == "XKF2" and x.C != 0) or (t == "VIBE" and x.IMU != 0):
            continue
        if t not in cols:
            cols[t] = x.get_fieldnames()
        rows[t].append([getattr(x, k) for k in cols[t]])
    L = {t: pd.DataFrame(r, columns=cols.get(t)) for t, r in rows.items()}
    g = L["GPS"]
    g = g[(g.Status >= 3) & (g.GWk > 0)]
    utc = GPS_EPOCH_UNIX + g.GWk * 604800 + g.GMS / 1e3 - leap
    k, b = np.polyfit(g.TimeUS / 1e6, utc, 1)
    resid = utc - (k * g.TimeUS / 1e6 + b)
    for t, d in L.items():
        if len(d) and "TimeUS" in d:
            d["utc"] = k * d.TimeUS / 1e6 + b
    L["_fit"] = {"slope_ppm": (k - 1) * 1e6, "resid_ms_p50": float(resid.abs().median() * 1e3), "fixes": len(g)}
    return L


def track(pos, home):
    """POS + home (Lat, Lng, Alt) -> utc, north_m, east_m, dist_m, alt_m, speed_ms (1 s smoothing)."""
    t = pos[["utc"]].copy()
    t["north_m"] = np.radians(pos.Lat - home.Lat) * R_EARTH
    t["east_m"] = np.radians(pos.Lng - home.Lng) * R_EARTH * math.cos(math.radians(home.Lat))
    t["dist_m"] = np.hypot(t.north_m, t.east_m)
    t["alt_m"] = pos.Alt - home.Alt
    dt = np.gradient(t.utc.values)
    vn, ve = np.gradient(t.north_m.values) / dt, np.gradient(t.east_m.values) / dt
    n = max(1, int(round(1.0 / np.median(dt))))
    t["speed_ms"] = pd.Series(np.hypot(vn, ve)).rolling(n, center=True, min_periods=1).mean().values
    return t


def _runs(mask, u, max_gap):
    """Contiguous runs of True in mask (gaps in u up to max_gap s allowed) -> list of (start, end) index pairs."""
    idx = np.flatnonzero(mask)
    if not len(idx):
        return []
    br = np.flatnonzero((np.diff(u[idx]) > max_gap) | (np.diff(idx) > 1))   # an unmasked sample breaks a run
    starts = np.r_[idx[0], idx[br + 1]]
    ends = np.r_[idx[br], idx[-1]]
    return list(zip(starts, ends))


def detect_hovers(tr, min_alt=5.0, min_dist=5.0, max_speed=1.0, min_hover_s=20.0, tol=2.0, t0=None, t1=None):
    """Hovers in a track (columns utc, dist_m, alt_m, speed_ms). Returns a list of dicts with the median
    distance and the +-tol window (start, end, s)."""
    tr = tr if t0 is None else tr[(tr.utc >= t0) & (tr.utc <= t1)]
    tr = tr.reset_index(drop=True)
    u = tr.utc.values
    still = (tr.speed_ms.values < max_speed) & (tr.alt_m.values > min_alt) & (tr.dist_m.values > min_dist)
    runs = [(u[s], u[e], float(np.median(tr.dist_m.values[s:e + 1])))
            for s, e in _runs(still, u, 1.0) if u[e] - u[s] >= 2.0]
    merged = []                                         # join short pieces of one hover (gusts, small moves)
    for r in runs:
        if merged and r[0] - merged[-1][1] < 15 and abs(r[2] - merged[-1][2]) < 5:
            a, _, _ = merged[-1]
            sel = (u >= a) & (u <= r[1])
            merged[-1] = (a, r[1], float(np.median(tr.dist_m.values[sel])))
        else:
            merged.append(r)
    out = []
    for a, b, d in merged:
        if b - a < min_hover_s:
            continue
        band = (np.abs(tr.dist_m.values - d) <= tol) & (tr.alt_m.values > min_alt)
        # the +-tol stretch that overlaps the still window most
        best = max(_runs(band, u, 1.0), key=lambda se: max(0.0, min(u[se[1]], b) - max(u[se[0]], a)))
        out.append({"dist_m": round(d, 1), "still_start": a, "still_end": b,
                    "start": u[best[0]], "end": u[best[1]], "dur_s": u[best[1]] - u[best[0]]})
    return out


def lean(att):
    """ATT -> thrust tilt (deg) per sample and mean horizontal thrust direction (deg, toward)."""
    ph, th, ps = np.radians(att.Roll), np.radians(att.Pitch), np.radians(att.Yaw)
    n = -(np.cos(ps) * np.sin(th) * np.cos(ph) + np.sin(ps) * np.sin(ph))
    e = -(np.sin(ps) * np.sin(th) * np.cos(ph) - np.cos(ps) * np.sin(ph))
    tilt = np.degrees(np.arcsin(np.clip(np.hypot(n, e), 0, 1)))
    return tilt, float(np.degrees(np.arcsin(min(1, np.hypot(n.mean(), e.mean()))))), \
        float(np.degrees(np.arctan2(e.mean(), n.mean())) % 360)


def win(d, a, b):
    return d[(d.utc >= a) & (d.utc <= b)]


def armed_intervals(L):
    """(arm_utc, disarm_utc) pairs. A log that starts armed (first ARM is a disarm with no arm before)
    starts its first interval at the log start."""
    arm = L["ARM"].sort_values("utc")
    start = L["ATT"].utc.min()
    out, cur = [], None
    for _, x in arm.iterrows():
        if x.ArmState == 1 and cur is None:
            cur = x.utc
        elif x.ArmState == 0:
            if cur is not None:
                out.append((cur, x.utc))
            elif not out and L["CTUN"].pipe(lambda c: (win(c, start, x.utc).ThO > 0.2).any()):
                out.append((start, x.utc))                 # armed before the log started
            cur = None
    if cur is not None:
        out.append((cur, L["ATT"].utc.max()))
    return out


def vibe_stats(v, prefix=""):
    d = {}
    for ax in ("VibeX", "VibeY", "VibeZ"):
        s = v[ax]
        d[f"{prefix}{ax.lower()}_mean"], d[f"{prefix}{ax.lower()}_p95"], d[f"{prefix}{ax.lower()}_max"] = \
            (s.mean(), s.quantile(.95), s.max()) if len(s) else (np.nan,) * 3
    d[f"{prefix}clips"] = int(v.Clip.max() - v.Clip.min()) if len(v) else 0
    return d


def analyse(L, min_alt=5.0, min_dist=5.0, max_speed=1.0, min_hover_s=20.0, tol=2.0):
    ts = lambda u: pd.Timestamp(u, unit="s", tz="UTC").tz_convert("America/Denver").strftime("%H:%M:%S.%f")[:-5]
    par = L["PARM"]
    # PARM is logged at log start and again whenever a parameter changes (e.g. MOT_THST_HOVER saved at disarm)
    param = lambda n, i=-1: float(par[par.Name == n].Value.iloc[i]) if (par.Name == n).any() else np.nan
    orgn = L["ORGN"][L["ORGN"].Type == 1]
    rows, text = [], []
    for fi, (t_arm, t_dis) in enumerate(armed_intervals(L), 1):
        o = orgn[orgn.utc <= t_arm + 2]
        home = (o if len(o) else orgn).iloc[-1]
        tr = track(L["POS"], home)
        trf = win(tr, t_arm, t_dis)
        bat, ct, vb, att = L["BAT"], L["CTUN"], L["VIBE"], L["ATT"]
        ev = L["EV"]
        to = win(ev, t_arm, t_dis)
        t_to = to[to.Id == 28].utc.min() if (to.Id == 28).any() else t_arm      # NOT_LANDED = takeoff
        lc = to[(to.Id == 18) & (to.utc > t_to)]
        t_ld = lc.utc.min() if len(lc) else t_dis                                  # LAND_COMPLETE
        b = win(bat, t_arm, t_dis)
        rest = win(bat, t_dis + 5, t_dis + 15)
        vair = win(vb, t_to + 3, t_ld - 1)
        cf = win(ct, t_arm, t_dis)
        disarm_pos = trf.iloc[-1]
        f = {"kind": "flight", "flight": fi, "arm": ts(t_arm), "takeoff": ts(t_to), "land_or_disarm": ts(t_ld),
             "disarm": ts(t_dis), "airborne_s": t_ld - t_to,
             "max_dist_m": trf.dist_m.max(), "max_alt_m": trf.alt_m.max(),
             "disarm_dist_m": disarm_pos.dist_m, "disarm_alt_m": disarm_pos.alt_m,
             "disarm_bearing_deg": math.degrees(math.atan2(disarm_pos.east_m, disarm_pos.north_m)) % 360,
             "v_arm": win(bat, t_arm - 2, t_arm + 1).Volt.mean(), "v_min": b.Volt.min(),
             "v_min_at": ts(b.utc[b.Volt.idxmin()]), "i_at_vmin": b.Curr[b.Volt.idxmin()],
             "v_disarm": b.Volt.iloc[-1], "v_rest_10s": rest.Volt.mean() if len(rest) else np.nan,
             "mah_used": b.CurrTot.iloc[-1] - b.CurrTot.iloc[0], "wh_used": b.EnrgTot.iloc[-1] - b.EnrgTot.iloc[0],
             "i_mean_air": win(bat, t_to + 5, t_ld - 5).Curr.mean(), "i_max": b.Curr.max(),
             "batt_capacity_mah": param("BATT_CAPACITY"), "batt_low_volt": param("BATT_LOW_VOLT"),
             "mot_thst_hover_first": param("MOT_THST_HOVER", 0), "mot_thst_hover_last": param("MOT_THST_HOVER"),
             "thh_arm": cf.ThH.iloc[0], "thh_end": cf.ThH.iloc[-1], "took_off": bool((to.Id == 28).any()),
             "tho_mean_air": win(ct, t_to + 5, t_ld - 5).ThO.mean(),
             "fence_radius_m": param("FENCE_RADIUS"), "fence_alt_max_m": param("FENCE_ALT_MAX"),
             "ekf_wind_nonzero": bool((win(L["XKF2"], t_to, t_ld)[["VWN", "VWE"]].abs() > 1e-6).any().any())}
        f.update(vibe_stats(vair))
        rows.append(f)
        hv = detect_hovers(tr, min_alt, min_dist, max_speed, min_hover_s, tol, t_to, t_ld)
        for h in hv:
            a_, b_ = h["start"], h["end"]
            tilt, tilt_mean, toward = lean(win(att, a_, b_))
            p = win(tr, a_, b_)
            c = win(ct, a_, b_)
            r = {"kind": "hover", "flight": fi, "hover_dist_m": h["dist_m"], "start": ts(a_), "end": ts(b_),
                 "dur_s": h["dur_s"], "still_start": ts(h["still_start"]), "still_end": ts(h["still_end"]),
                 "dist_min_m": p.dist_m.min(), "dist_max_m": p.dist_m.max(),
                 "alt_mean_m": p.alt_m.mean(), "alt_min_m": p.alt_m.min(), "alt_max_m": p.alt_m.max(),
                 "lean_mean_deg": tilt.mean(), "lean_p95_deg": np.percentile(tilt, 95),
                 "thrust_tilt_mean_deg": tilt_mean, "lean_toward_deg": toward,
                 "tho_mean": c.ThO.mean(), "thh_mean": c.ThH.mean(),
                 "i_mean": win(bat, a_, b_).Curr.mean(), "v_mean": win(bat, a_, b_).Volt.mean(),
                 "_start_utc": a_, "_end_utc": b_}
            r.update(vibe_stats(win(vb, a_, b_)))
            rows.append(r)
        # text
        text += [f"Flight {fi}: armed {f['arm']} - disarmed {f['disarm']}; takeoff {f['takeoff']}, "
                 f"land/disarm {f['land_or_disarm']} ({f['airborne_s']:.0f} s); max {f['max_dist_m']:.1f} m, "
                 f"{f['max_alt_m']:.1f} m; at disarm {f['disarm_dist_m']:.1f} m from home, bearing "
                 f"{f['disarm_bearing_deg']:.0f} deg, altitude {f['disarm_alt_m']:.1f} m",
                 f"  battery: {f['v_arm']:.2f} V at arm, min {f['v_min']:.2f} V at {f['v_min_at']} ({f['i_at_vmin']:.1f} A), "
                 f"{f['v_disarm']:.2f} V at disarm, {f['v_rest_10s']:.2f} V 10 s later; {f['mah_used']:.0f} mAh of "
                 f"{f['batt_capacity_mah']:.0f}, {f['wh_used']:.1f} Wh; mean {f['i_mean_air']:.1f} A airborne, max {f['i_max']:.1f} A",
                 f"  throttle: ThO mean airborne {f['tho_mean_air']:.3f}; ThH (hover throttle estimate) {f['thh_arm']:.3f} at arm, "
                 f"{f['thh_end']:.3f} at disarm; MOT_THST_HOVER in the log {f['mot_thst_hover_first']:.3f} (first) / "
                 f"{f['mot_thst_hover_last']:.3f} (last)" + ("" if f['took_off'] else "  [no takeoff in this arm cycle]"),
                 f"  VIBE airborne X/Y/Z mean {f['vibex_mean']:.1f}/{f['vibey_mean']:.1f}/{f['vibez_mean']:.1f}, p95 "
                 f"{f['vibex_p95']:.1f}/{f['vibey_p95']:.1f}/{f['vibez_p95']:.1f}, max {f['vibex_max']:.1f}/"
                 f"{f['vibey_max']:.1f}/{f['vibez_max']:.1f} m/s/s; clips +{f['clips']}",
                 f"  EKF wind states {'present' if f['ekf_wind_nonzero'] else 'all zero (not estimated)'}; "
                 f"fence radius {f['fence_radius_m']:.0f} m, alt max {f['fence_alt_max_m']:.0f} m"]
        for r in [x for x in rows if x["kind"] == "hover" and x["flight"] == fi]:
            text.append(f"  hover {r['hover_dist_m']:.1f} m: {r['start']} - {r['end']} ({r['dur_s']:.0f} s within +-{tol:g} m; "
                        f"still {r['still_start']} - {r['still_end']}); dist {r['dist_min_m']:.1f}-{r['dist_max_m']:.1f}, "
                        f"alt {r['alt_mean_m']:.1f} ({r['alt_min_m']:.1f}-{r['alt_max_m']:.1f}); lean {r['lean_mean_deg']:.1f} deg "
                        f"(p95 {r['lean_p95_deg']:.1f}), thrust tilt {r['thrust_tilt_mean_deg']:.1f} deg toward "
                        f"{r['lean_toward_deg']:.0f} deg; ThO {r['tho_mean']:.3f}; {r['i_mean']:.1f} A at {r['v_mean']:.2f} V; "
                        f"VIBE mean {r['vibex_mean']:.1f}/{r['vibey_mean']:.1f}/{r['vibez_mean']:.1f}, clips +{r['clips']}")
    return pd.DataFrame(rows), text


def events(L):
    ts = lambda u: pd.Timestamp(u, unit="s", tz="UTC").tz_convert("America/Denver").strftime("%H:%M:%S.%f")[:-5]
    ev = []
    for _, x in L["MODE"].iterrows():
        ev.append((x.utc, f"MODE {MODES.get(int(x.Mode), int(x.Mode))}"))
    for _, x in L["MSG"].iterrows():
        if not any(x.Message.startswith(b) or b in x.Message for b in BANNER):
            ev.append((x.utc, f"MSG  {x.Message}"))
    for _, x in L["ERR"].iterrows():
        ev.append((x.utc, f"ERR  subsys {int(x.Subsys)} code {int(x.ECode)}"))
    for _, x in L["EV"].iterrows():
        ev.append((x.utc, f"EV   {EVENTS.get(int(x.Id), int(x.Id))}"))
    for _, x in L["ARM"].iterrows():
        ev.append((x.utc, f"ARM  {'armed' if x.ArmState else 'disarmed'} (method {int(x.Method)})"))
    return [f"  {ts(u)}  {s}" for u, s in sorted(ev, key=lambda e: e[0])]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("bin")
    p.add_argument("--hovers", default=None, help="planned hover distances, m (compared with the detected ones)")
    p.add_argument("--warn-m", type=float, default=2.0)
    p.add_argument("--min-alt", type=float, default=5.0, help="hover: altitude above this, m")
    p.add_argument("--min-dist", type=float, default=5.0, help="hover: distance from home above this, m")
    p.add_argument("--max-speed", type=float, default=1.0, help="hover: horizontal speed below this (1 s mean), m/s")
    p.add_argument("--min-hover-s", type=float, default=20.0)
    p.add_argument("--tol", type=float, default=2.0, help="hover window: distance within +- this, m")
    p.add_argument("--leap", type=int, default=18)
    p.add_argument("--out", default=None)
    a = p.parse_args()
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.bin)),
                                os.path.splitext(os.path.basename(a.bin))[0].replace(" ", "_") + "_state")
    os.makedirs(out, exist_ok=True)
    L = load_log(a.bin, a.leap)
    df, text = analyse(L, a.min_alt, a.min_dist, a.max_speed, a.min_hover_s, a.tol)
    fit = L["_fit"]
    head = [f"# {os.path.basename(a.bin)}",
            f"GPS -> UTC fit: {fit['fixes']} fixes, slope {fit['slope_ppm']:+.1f} ppm, |residual| p50 {fit['resid_ms_p50']:.1f} ms. "
            f"Times MST. Hovers: speed < {a.max_speed:g} m/s for >= {a.min_hover_s:g} s, alt > {a.min_alt:g} m, "
            f"dist > {a.min_dist:g} m; window = distance within +-{a.tol:g} m. Lean toward = wind from (hypothesis).", ""]
    warn = []
    if a.hovers:
        det = df[df.kind == "hover"].hover_dist_m.tolist() if len(df) else []
        for h in [float(x) for x in a.hovers.split(",")]:
            near = min(det, key=lambda d: abs(d - h)) if det else None
            if near is None or abs(near - h) > a.warn_m:
                warn.append(f"WARNING: planned hover {h:g} m: nearest detected {near if near is not None else 'none'} m "
                            f"(differs by more than {a.warn_m:g} m); use the detected distance for --hovers")
            else:
                warn.append(f"planned hover {h:g} m: detected {near:g} m")
    lines = head + text + ([""] + warn if warn else []) + ["", "Events:"] + events(L)
    df.drop(columns=[c for c in df.columns if c.startswith("_")]).to_csv(os.path.join(out, "flight_state.csv"), index=False)
    open(os.path.join(out, "flight_state.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {out}/flight_state.csv, flight_state.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
