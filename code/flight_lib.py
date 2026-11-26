"""Flight schedules for run_field.py --schedule: build, print for the pilot, split the data."""
import csv, json, os, re, shutil, time
import pandas as pd


def parse_spec(spec):
    """'qos0:120,qos1:120,qos2:120' -> [(0, 120), (1, 120), (2, 120)]"""
    out = []
    for part in spec.split(","):
        m = re.fullmatch(r"\s*qos([012]):(\d+(?:\.\d+)?)\s*", part)
        if not m:
            raise ValueError(f"bad schedule item {part!r} (want qos<0|1|2>:<seconds>)")
        out.append((int(m.group(1)), float(m.group(2))))
    return out


def parse_specs(spec, n_points):
    """Spec per point. Without '/': the same spec at every point. With '/': one spec per point,
    in point order, e.g. 'qos0:40,qos1:40/qos1:40,qos0:40' for two points."""
    parts = spec.split("/")
    if len(parts) == 1:
        return [parse_spec(spec)] * n_points
    if len(parts) != n_points:
        raise ValueError(f"schedule has {len(parts)} '/'-separated specs but there are {n_points} points")
    return [parse_spec(x) for x in parts]


def build(spec, points, distances, launch_unix, start_delay_s, gap_s, move_s, imu_hz, nodelay):
    """Segments for every hover point, back to back; returns the schedule dict."""
    per_point = parse_specs(spec, len(points))
    if distances and len(distances) != len(points):
        raise ValueError("--point-distances must have one value per point")
    t = launch_unix + start_delay_s
    segs, n = [], 0
    for pi_, pt in enumerate(points):
        if pi_ > 0:
            t += move_s - gap_s                      # move between points replaces the last gap
        for q, dur in per_point[pi_]:
            n += 1
            segs.append({"label": f"s{n:02d}_{pt}_qos{q}", "point": pt,
                         "distance_m": distances[pi_] if distances else None,
                         "qos": q, "duration_s": dur, "start_unix": t, "end_unix": t + dur})
            t += dur + gap_s
    return {"spec": spec, "points": points, "distances": distances, "launch_unix": launch_unix,
            "start_delay_s": start_delay_s, "gap_s": gap_s, "move_s": move_s, "imu_hz": imu_hz,
            "nodelay": nodelay, "segments": segs, "end_unix": segs[-1]["end_unix"] if segs else t}


def hms(t):
    return time.strftime("%H:%M:%S", time.localtime(t))


def timetable(sched):
    s = sched["segments"]
    lines = [f"Flight timetable (laptop/Pi clock, {time.strftime('%Z')}). Launch {hms(sched['launch_unix'])}; "
             f"first segment {hms(s[0]['start_unix'])} (take off and reach the first point before it).", ""]
    for pt in sched["points"]:
        ps = [x for x in s if x["point"] == pt]
        d = ps[0]["distance_m"]
        lines.append(f"Hover point {pt}" + (f" ({d:g} m)" if d is not None else "") +
                     f": hold {hms(ps[0]['start_unix'])} - {hms(ps[-1]['end_unix'])}"
                     f" ({ps[-1]['end_unix'] - ps[0]['start_unix']:.0f} s)")
        for x in ps:
            lines.append(f"    {x['label']:<18} QoS {x['qos']}  {hms(x['start_unix'])} - {hms(x['end_unix'])}"
                         f"  ({x['duration_s']:.0f} s)")
    lines += ["", f"Follow the flight plan (RTL at the planned time); last segment ends {hms(sched['end_unix'])}. "
              f"Total {(sched['end_unix'] - sched['launch_unix']) / 60:.1f} min from launch."]
    return "\n".join(lines)


def split(fdir, flight):
    """Make one run folder per segment from the flight folder.

    Needs fdir/rx_all.csv (laptop logger, whole flight), fdir/segments.csv (Pi launcher) and
    fdir/pi_segments/<label>/pi_log.csv. Each segment's rx rows are those of its topics with
    t_pub_ns inside the segment's actual [start, end] (sequence numbers restart per segment).
    """
    rx = pd.read_csv(os.path.join(fdir, "rx_all.csv"))
    segs = pd.read_csv(os.path.join(fdir, "segments.csv"))
    plan = {x["label"]: x for x in flight["schedule"]["segments"]}
    made = []
    for _, sg in segs.iterrows():
        lab = sg["label"]
        if pd.isna(sg["actual_start_unix"]):          # skipped by the launcher (late); nothing was published
            continue
        src = os.path.join(fdir, "pi_segments", lab)
        sdir = os.path.join(fdir, lab)
        os.makedirs(sdir, exist_ok=True)
        for f in ("pi_log.csv", "publisher.out"):
            if os.path.exists(os.path.join(src, f)):
                shutil.copy2(os.path.join(src, f), os.path.join(sdir, f))
        lo, hi = sg["actual_start_unix"] * 1e9, sg["end_unix"] * 1e9
        rx[(rx.t_pub_ns >= lo) & (rx.t_pub_ns <= hi)].to_csv(os.path.join(sdir, "rx.csv"), index=False)
        p = plan.get(lab, {})
        meta = {k: flight.get(k) for k in ("session", "notes", "pi_height_m", "router_height_m", "nodelay",
                                           "imu_hz", "sidelog", "stadump_s", "git_commit", "paho_laptop",
                                           "mosquitto", "pi_kernel", "bmp_hz", "ina_hz")}
        meta.update(mode="flight_segment", flight=flight["label"], label=lab, run_id=lab,
                    point=sg["point"], distance_m=p.get("distance_m"), qos=int(sg["qos"]),
                    duration_s=float(sg["duration_s"]), planned_start_unix=float(sg["planned_start_unix"]),
                    start_unix=float(sg["actual_start_unix"]), end_unix=float(sg["end_unix"]),
                    late_s=float(sg["late_s"]), publisher_rc=int(sg["rc"]),
                    run_s=float(sg["run_s"]) if "run_s" in sg and not pd.isna(sg["run_s"]) else float(sg["duration_s"]),
                    note=None if pd.isna(sg["note"]) else sg["note"],
                    side_dir="../pi_side", chrony_after="../chrony_after.txt")
        json.dump(meta, open(os.path.join(sdir, "meta.json"), "w"), indent=2)
        made.append(lab)
    return made
