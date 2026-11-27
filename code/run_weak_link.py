#!/usr/bin/env python3
"""Weak-signal QoS 2 bench test: one run_field.py flight-mode call per Pi position.

Session (campaign) weak_link_<position>, label r<N>. One detached launcher on the Pi runs
--rounds x (QoS 0, 1, 2) segments of --seg-s, the order rotated every round
(0-1-2, 1-2-0, 2-0-1, 0-1-2, ...), so each QoS takes each slot of a round equally often.
Everything else is run_field.py, unchanged:
  - publisher: all three sensors at nominal rates (IMU 20 Hz, BMP280 2 Hz, INA219 2 Hz), TCP_NODELAY
    (--nodelay 1), as in the flights;
  - packet capture for the whole run (--pcap 1): enp0s31f6 + lo, with MQTT CONNECT segments
    filtered out (campaign_lib.PCAP_FILTER), so no credential is stored;
  - Pi side logs (--sidelog 1 --stadump 1): station dump every 1 s (signal, tx/rx bitrate, tx failed,
    tx packets; brcmfmac reports no retry counter), iw events, chrony every 10 s, vcgencmd
    (throttled = under-voltage flag) every 1 s;
  - power gate and chrony start gate before the launch (run_field.py refuses on failure).
Analyse afterwards with: python analysis/weak_link_qos2.py data/weak_link_<position>/r<N> [...]

  python code/run_weak_link.py --position p2m --distance-m 2 --notes "..." [--dry-run]
"""
import argparse, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("--position", required=True, help="position label, e.g. p2m, wall1 ([A-Za-z0-9_.-])")
p.add_argument("--label", default="r1", help="run label inside the session (repeat at one position: r2, ...)")
p.add_argument("--distance-m", type=float, default=None, help="Pi to router distance, m")
p.add_argument("--notes", default="", help="position, obstacles, antenna orientation, ...")
p.add_argument("--rounds", type=int, default=6)
p.add_argument("--seg-s", type=float, default=20.0)
p.add_argument("--gap-s", type=float, default=3.0)
p.add_argument("--start-delay-s", type=float, default=10.0, help="launch -> first segment")
p.add_argument("--dry-run", action="store_true", help="run_field.py --dry-run: print the plan and commands only")
a, extra = p.parse_known_args()
if not re.fullmatch(r"[A-Za-z0-9_.-]+", a.position):
    sys.exit("--position: use letters, digits, _ . - only")

order = [0, 1, 2]
segs = []
for r in range(a.rounds):
    k = r % 3
    segs += [f"qos{q}:{a.seg_s:g}" for q in order[k:] + order[:k]]
spec = ",".join(segs)
total = a.start_delay_s + a.rounds * 3 * a.seg_s + (a.rounds * 3 - 1) * a.gap_s
notes = (f"weak-link QoS 2 bench test, position {a.position}; {a.rounds} rounds x QoS 0/1/2 x {a.seg_s:g} s, "
         f"order rotated per round, gap {a.gap_s:g} s; Pi on wall power; capture on; " + a.notes).strip()
cmd = [sys.executable, os.path.join(HERE, "run_field.py"),
       "--session", f"weak_link_{a.position}", "--label", a.label,
       "--schedule", spec, "--points", a.position,
       "--start-delay-s", f"{a.start_delay_s:g}", "--gap-s", f"{a.gap_s:g}", "--move-s", "0",
       "--nodelay", "1", "--sidelog", "1", "--stadump", "1", "--pcap", "1", "--ping", "0",
       "--notes", notes] + (["--point-distances", f"{a.distance_m:g}"] if a.distance_m is not None else []) \
      + (["--dry-run"] if a.dry_run else []) + extra
print(f"weak_link_{a.position}/{a.label}: {a.rounds * 3} segments, ~{total / 60:.1f} min of publishing "
      f"(+ ~1.5 min gates, + collection)\n  order: " +
      " | ".join("-".join(s.split(":")[0][3:] for s in segs[i:i + 3]) for i in range(0, len(segs), 3)))
sys.exit(subprocess.call(cmd))
