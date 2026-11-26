#!/usr/bin/env python3
"""Checks of the chrony reading parser and start gate on chronyc output seen on the Pi, and of the
power gate (vcgencmd get_throttled).
Run: python tests/test_campaign_lib.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "code"))
from campaign_lib import (chrony_reading, chrony_gate, split_gate_output, parse_lastrx,
                          power_gate, POWER_GATE_N, POWER_GATE_CMD)

HDR = ("MS Name/IP address         Stratum Poll Reach LastRx Last sample\n"
       "===============================================================================\n"
       "^? 138.68.201.49                 3  10     0  309m    +21ms[+8540us] +/-   99ms\n")

def reading(lastrx, offset_ms=0.02, state="^*", reach="377", server="192.168.1.4", sample="+12us[ +16us]",
            err="22ms", update=4.0):
    sign = "fast" if offset_ms >= 0 else "slow"
    return (HDR + f"{state} {server}                   4   2   {reach}   {lastrx}   {sample} +/-   {err}\n"
            f"Reference ID    : C0A80104 (192.168.1.4)\n"
            f"System time     : {abs(offset_ms) / 1e3:.9f} seconds {sign} of NTP time\n"
            f"Last offset     : +0.000039085 seconds\n"
            f"Update interval : {update} seconds\n")

fails = 0
def check(name, got, want, detail=""):
    global fails
    fails += got != want
    print(f"{'PASS' if got == want else 'FAIL'}  {name}: {got} {detail}")

# single reading
r = chrony_reading(reading(31), reading(31))
check("reading parses LastRx 31", r["lastrx_s"], 31)
check("reading parses offset", round(r["offset_ms"], 3), 0.02)
check("reading parses last sample (offset part only)", r["last_sample"], "+12us[ +16us]")
check("reading parses update interval", r["update_interval_s"], 4.0)
check("reading: missing server -> error", "error" in chrony_reading(reading(1, server="10.0.0.1"), ""), True)

cases = [
    # (name, LastRx readings, offsets, extra kwargs, expect ok)
    ("normal over Wi-Fi (2026-11-21: 24,1,6,11,16,21,26)", [24, 1, 6, 11, 16, 21, 26], None, {}, True),
    ("slow but alive, none <= 10 s (31,16,12,15,30,13,12)", [31, 16, 12, 15, 30, 13, 12], None, {}, False),
    ("stalled after reconnect (38..160)", [38, 50, 61, 88, 111, 127, 160], None, {}, False),
    ("one fresh reading, then a stall reading", [1, 5, 9, 13, 17, 21, "5m"], None, {}, False),
    ("healthy after restart (1-4 s)", [1, 2, 3, 4, 1, 2, 3], None, {}, True),
    ("offset 1.2 ms in one reading", [1, 2, 3, 4, 1, 2, 3], [0.02] * 6 + [-1.2], {}, False),
    ("not selected in one reading", [1, 2, 3, 4, 1, 2, 3], None, {"state_at": (3, "^+")}, False),
    ("exactly at limits (LastRx 60, one 10, offset 1.0)", [60, 10, 60], [1.0, -1.0, 0.5], {}, True),
    # 2026-11-22, both passed the old gate and were stalls (grew to 118 s, last sample frozen)
    ("rising 1..31, last sample frozen (old 7-reading gate)", [1, 6, 11, 16, 21, 26, 31], None, {"frozen": 1}, False),
    ("rising 2..62 over 13 readings, frozen", list(range(2, 63, 5)), None, {"frozen": 1}, False),
    ("rising 2..57 over 12 readings, frozen (all <= 60 s)", list(range(2, 58, 5)), None, {"frozen": 1}, False),
    # healthy but slow (update interval ~20 s): one reset inside 60 s
    ("slow healthy, 13 readings, one reset (24,1,..,26,2,..,27)",
     [24, 1, 6, 11, 16, 21, 26, 2, 7, 12, 17, 22, 27], None, {}, True),
    ("healthy, 4 s updates (1,2,3,4,1,..)", [1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4, 1], None, {}, True),
    # new sample seen only as a changed last sample (LastRx never drops between readings)
    ("LastRx rising but last sample changes", [1, 6, 11], None, {"samples": ["+12us[ +16us]", "-40us[ -38us]", "-40us[ -38us]"]}, True),
    # +/- error grows with time since the sample: must not count as a new sample
    ("frozen sample, only the +/- error grows", [1, 6, 11, 16], None, {"frozen": 1, "errs": ["22ms", "23ms", "24ms", "25ms"]}, False),
    ("single reading", [1], None, {}, False),
]
for name, lrx, offs, kw, expect in cases:
    offs = offs or [0.02] * len(lrx)
    txt = []
    samp, prev = 0, None
    for i, (x, o) in enumerate(zip(lrx, offs)):
        st = kw["state_at"][1] if "state_at" in kw and kw["state_at"][0] == i else "^*"
        if prev is not None and parse_lastrx(str(x)) < parse_lastrx(str(prev)) and "frozen" not in kw:
            samp += 1                       # a new sample: LastRx dropped, the sample value changes
        prev = x
        sample = kw["samples"][i] if "samples" in kw else f"+{12 + samp}us[ +16us]"
        err = kw["errs"][i] if "errs" in kw else "22ms"
        txt.append(reading(x, o, state=st, sample=sample, err=err))
    gate_output = "".join(t + "=== READING\n" for t in txt)        # as GATE_CMD prints it
    ok, d = chrony_gate(split_gate_output(gate_output))
    check(f"gate: {name}", ok, expect, f"({d['reason']})")
check("gate: no readings", chrony_gate([])[0], False)
for tok, want in [("0", 0), ("38", 38), ("5m", 300), ("309m", 18540), ("2h", 7200), ("-", float("inf"))]:
    check(f"LastRx '{tok}'", parse_lastrx(tok), want)

# power gate: output of POWER_GATE_CMD (get_throttled lines separated by '=== THROTTLED')
def thr(*vals):
    return "".join(f"throttled={v}\n=== THROTTLED\n" for v in vals)

for name, text, expect in [
    ("all 0x0", thr(*["0x0"] * POWER_GATE_N), True),
    ("ref1/f1b state 0x50005 in all", thr(*["0x50005"] * 5), False),
    ("under-voltage now in one reading only (0x1 then 0x10001)", thr("0x0", "0x0", "0x10001", "0x10000", "0x10000"), False),
    ("sticky 0x10000 only (earlier under-voltage, none now)", thr(*["0x10000"] * 5), False),
    ("sticky 0x50000 (under-voltage + throttling since boot)", thr(*["0x50000"] * 5), False),
    ("throttled since boot 0x40000, no under-voltage", thr(*["0x40000"] * 5), True),
    ("soft temp limit 0x80008, no under-voltage", thr(*["0x80008"] * 5), True),
    ("no output (SSH failed)", "", False),
    ("garbage output", "VCHI initialization failed\n", False),
]:
    ok, d = power_gate(text)
    check(f"power gate: {name}", ok, expect, f"({d['reason']}; bits {d.get('bits')})")
ok, d = power_gate(thr("0x50005"))
check("power gate: decodes 0x50005", d["bits"],
      ["under-voltage now", "throttled now", "under-voltage since boot", "throttled since boot"])
check("power gate cmd: 5 readings over 10 s", (POWER_GATE_N, POWER_GATE_CMD.count("sleep 2.5")), (5, 1))
sys.exit(1 if fails else 0)
