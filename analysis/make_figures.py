#!/usr/bin/env python3
"""Data figures for the paper (Figs. 2-8). No Pi, no network: reads existing data/ outputs.

One function per figure; each saves paper_figs/figN_<name>.png (300 dpi) and .pdf and prints n per
series plus the key numbers to check against the paper's tables.

Style: Liberation Serif, 8 pt labels, 7 pt ticks, 6.5 in wide, no titles, light grey grid, top/right
spines off, panel letters top left. QoS encoding is fixed everywhere (colour + line style + marker,
since orange/green are low-contrast on white): QoS 0 #257de0 solid/circle, QoS 1 #f47230
dashed/square, QoS 2 #00b894 dash-dot/triangle. The 20 ms threshold is a thin grey dotted line.
Palette check (OKLab x100, Machado CVD): normal 23-35, protan 15-27, deutan 13-34, tritan 11-33 for
every pair (target >= 8); contrast on white 4.1 / 2.9 / 2.5:1, so identity never relies on colour alone.

Inputs (all under data_processed/, or $UAV_MQTT_DATA; processed outputs only, no raw logs):
  Fig 2  base_final/qos*_rep*/{rx.csv, scans.csv}
  Fig 3  pcap_q2{,_nd}/qos2_rep1/{handshake.csv, rx.csv} (broker set_tcp_nodelay off / on, same session;
         handshake.csv from analysis/pcap_qos2_handshake.py); base20 / base20_nd QoS 2 rx.csv printed for comparison
  Fig 4  L1/qos1_rep1/{rx.csv, ping_pi.csv, scans.csv} (bgscan on, 50 Hz ping)
  Fig 5  field_2026-11-22/f1b/{position/track.csv, position/msgs_pos.csv, rssi.csv, scans.csv},
         field_2026-11-22/pixhawk/<log>_state/flight_state.{csv,txt}
  Fig 6  field_2026-11-24/f{3,4}/... as Fig 5 (distance from the router: flight_position.py --origin)
  Fig 7  f1b, f2b, f3, f4 position/msgs_pos.csv + rssi.csv + scans.csv (same exclusions as link_bands.py)
  Fig 8  bench_outage_2026-11-24/{A_q0_o60, A_q1_o60, A_q2_o60, B_q2_o60}/{outage.json, segments.csv, sent.csv, rx_all.csv}
Usage: python analysis/make_figures.py [2 3 4 5 6 7 8]   (default: all)
"""
import json, os, re, sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
D = os.environ.get("UAV_MQTT_DATA", os.path.join(ROOT, "data_processed"))
OUT = os.environ.get("UAV_MQTT_FIGS", os.path.join(ROOT, "paper_figs"))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
TZ = "America/Denver"

QOS = {0: dict(color="#257de0", ls="-", marker="o", label="QoS 0"),
       1: dict(color="#f47230", ls="--", marker="s", label="QoS 1"),
       2: dict(color="#00b894", ls="-.", marker="^", label="QoS 2")}
GREY, INK = "#6b6b6b", "#222222"
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Liberation Serif"], "font.size": 8,
    "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.6,
    "axes.edgecolor": "#444444", "axes.labelcolor": INK, "xtick.color": "#444444",
    "ytick.color": "#444444", "xtick.major.width": 0.5, "ytick.major.width": 0.5,
    "xtick.minor.width": 0.4, "ytick.minor.width": 0.4, "axes.grid": True, "axes.axisbelow": True,
    "grid.color": "#d9d9d9", "grid.linewidth": 0.4, "legend.frameon": False,
    "savefig.dpi": 300, "pdf.fonttype": 42, "ps.fonttype": 42, "lines.linewidth": 1.2,
})


# ------------------------------------------------------------------ helpers
def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(OUT, f"{name}.{ext}"), dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print(f"  saved paper_figs/{name}.png/.pdf")


def letter(ax, s):
    ax.annotate(f"({s})", xy=(0, 1), xycoords="axes fraction", xytext=(-2, 4), textcoords="offset points",
                ha="right", va="bottom", fontsize=8, color=INK)


def thr20(ax, axis="x"):
    (ax.axvline if axis == "x" else ax.axhline)(20, color=GREY, lw=0.6, ls=":", zorder=1)


def ccdf(ax, v, q, **kw):
    v = np.sort(np.asarray(v, float))
    y = 1.0 - np.arange(len(v)) / len(v)          # P(X >= x), last point 1/n
    st = QOS[q]
    ax.step(v, y, where="post", color=st["color"], ls=st["ls"], lw=1.1, label=kw.pop("label", st["label"]))
    m = int(np.argmax(v))                          # marker at the max (where the step ends)
    ax.plot(v[m], y[m], st["marker"], color=st["color"], ms=3.5, mec="white", mew=0.4)


def log_ms_axis(ax, which="x", lo=1, hi=200):
    (ax.set_xscale if which == "x" else ax.set_yscale)("log")
    (ax.set_xlim if which == "x" else ax.set_ylim)(lo, hi)
    fmt = FuncFormatter(lambda v, p: f"{v:g}")
    axis = ax.xaxis if which == "x" else ax.yaxis
    axis.set_major_locator(LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
    axis.set_major_formatter(fmt)
    axis.set_minor_formatter(NullFormatter())


def scans_of(folder):
    """Completed Wi-Fi scans (start, end) of a run or flight: <folder>/scans.csv (from the Pi's iw event log)."""
    p = os.path.join(folder, "scans.csv")
    if not os.path.exists(p):
        return []
    s = pd.read_csv(p)
    return list(zip(s.start_unix, s.end_unix))


def station(folder):
    """Pi station-dump series of a flight: <folder>/rssi.csv -> columns t, signal (dBm), tx_bitrate, ..."""
    return pd.read_csv(os.path.join(folder, "rssi.csv")).rename(
        columns={"t_unix": "t", "signal_dbm": "signal", "tx_bitrate_mbps": "tx_bitrate", "rx_bitrate_mbps": "rx_bitrate"})


def q_stats(L):
    L = pd.Series(L, dtype=float)
    return (f"n={len(L)} p50={L.median():.2f} p95={L.quantile(.95):.2f} p99={L.quantile(.99):.2f} "
            f"max={L.max():.2f} >20ms={100 * (L > 20).mean():.2f}%")


def flight_state_csv(binpath):
    stem = os.path.splitext(os.path.basename(binpath))[0].replace(" ", "_")
    p = os.path.join(os.path.dirname(binpath), f"{stem}_state", "flight_state.csv")
    if not os.path.exists(p):
        sys.exit(f"missing {p} (flight_state.py output for {os.path.basename(binpath)})")
    return p


def clock_to_unix(hms, day):
    return pd.Timestamp(f"{day} {hms}", tz=TZ).timestamp()


def events_txt(binpath):
    stem = os.path.splitext(os.path.basename(binpath))[0].replace(" ", "_")
    return open(os.path.join(os.path.dirname(binpath), f"{stem}_state", "flight_state.txt")).read()


def legend_qos(ax, qs=(0, 1, 2), loc="best", marker_only=False, **kw):
    from matplotlib.lines import Line2D
    h = [Line2D([], [], color=QOS[q]["color"], ls="none" if marker_only else QOS[q]["ls"],
                marker=QOS[q]["marker"], ms=4, mec="white", mew=0.4, lw=1.1, label=QOS[q]["label"]) for q in qs]
    ax.legend(handles=h, loc=loc, handlelength=2.2, **kw)


def scatter_qos(ax, t, y, q, s=3, alpha=0.55):
    st = QOS[q]
    ax.scatter(t, y, s=s, marker=st["marker"], color=st["color"], alpha=alpha, lw=0, rasterized=True)


# ------------------------------------------------------------------ Fig 2
def fig2():
    print("Fig 2: latency CCDF, base_final")
    fig, axs = plt.subplots(1, 2, figsize=(6.5, 2.6), sharey=True, constrained_layout=True)
    for q in (0, 1, 2):
        allL, keep = [], []
        for rep in range(1, 6):
            r = os.path.join(D, "base_final", f"qos{q}_rep{rep}")
            rx = pd.read_csv(os.path.join(r, "rx.csv"))
            tp = rx.t_pub_ns.values / 1e9
            mask = np.zeros(len(rx), bool)
            for s0, s1 in scans_of(r):
                mask |= (tp >= s0 - 1) & (tp <= s1 + 1)
            allL.append(rx.latency_ms.values)
            keep.append(rx.latency_ms.values[~mask])
        a, k = np.concatenate(allL), np.concatenate(keep)
        ccdf(axs[0], a, q)
        ccdf(axs[1], k, q)
        print(f"  QoS {q} all:        {q_stats(a)}")
        print(f"  QoS {q} w/o scans:  {q_stats(k)}  (removed {len(a) - len(k)})")
    for i, ax in enumerate(axs):
        log_ms_axis(ax, "x", 1, 200)
        ax.set_yscale("log")
        ax.set_ylim(1e-5, 1.3)
        ax.set_xlabel("Latency (ms)")
        thr20(ax)
        letter(ax, "ab"[i])
    axs[0].set_ylabel("P(latency ≥ x)")
    legend_qos(axs[0], loc="lower left")
    axs[1].text(0.98, 0.97, "scan windows ±1 s removed", transform=axs[1].transAxes, ha="right", va="top",
                fontsize=7, color=GREY)
    save(fig, "fig2_bench_ccdf")


# ------------------------------------------------------------------ Fig 3
def fig3():
    print("Fig 3: broker Nagle (set_tcp_nodelay) effect on QoS 2")
    from matplotlib.lines import Line2D
    fig, axs = plt.subplots(1, 2, figsize=(6.5, 2.4), constrained_layout=True)
    runs = [("pcap_q2", "Broker Nagle on", "-", "#8a8a8a"), ("pcap_q2_nd", "Broker Nagle off\n(set_tcp_nodelay)", "-", QOS[2]["color"])]
    for camp, lab, ls, col in runs:
        h = pd.read_csv(os.path.join(D, camp, "qos2_rep1", "handshake.csv"))
        v = h.a_rec_ms.dropna().values
        rx = pd.read_csv(os.path.join(D, camp, "qos2_rep1", "rx.csv"))
        for ax, vals in ((axs[0], v), (axs[1], rx.latency_ms.values)):
            s = np.sort(vals)
            y = 1 - np.arange(len(s)) / len(s)
            dash = "-" if camp == "pcap_q2_nd" else (0, (1.2, 1.2))
            ax.step(s, y, where="post", color=col, ls=dash, lw=1.2, label=lab)
            ax.plot(s[-1], y[-1], "^" if camp == "pcap_q2_nd" else "D", color=col, ms=3.5, mec="white", mew=0.4)
        print(f"  {camp}: PUBLISH->PUBREC {q_stats(v)}")
        print(f"  {camp}: end-to-end    {q_stats(rx.latency_ms)}")
    for camp in ("base20", "base20_nd"):
        L = pd.concat([pd.read_csv(os.path.join(D, camp, f"qos2_rep{r}", "rx.csv")).latency_ms for r in range(1, 6)])
        print(f"  (alternative for b, different sessions) {camp} QoS 2: {q_stats(L)}")
    axs[0].set_xscale("log"); axs[0].set_xlim(0.1, 100)
    axs[0].xaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:g}"))
    axs[0].set_xlabel("Broker PUBLISH → PUBREC delay (ms)")
    log_ms_axis(axs[1], "x", 1, 200)
    axs[1].set_xlabel("End-to-end latency, QoS 2 (ms)")
    thr20(axs[1])
    for i, ax in enumerate(axs):
        ax.set_yscale("log"); ax.set_ylim(1e-3, 1.3)
        ax.set_ylabel("P(delay ≥ x)" if i == 0 else "P(latency ≥ x)")
        letter(ax, "ab"[i])
    for ax in axs:
        # narrow enough to sit right of the 20 ms line in (b), clear of both curves
        ax.legend(loc="upper right", handlelength=1.8, handletextpad=0.5)
    save(fig, "fig3_broker_nagle")


# ------------------------------------------------------------------ Fig 4
def fig4():
    print("Fig 4: one background-scan episode, L1")
    r = os.path.join(D, "L1", "qos1_rep1")
    rx = pd.read_csv(os.path.join(r, "rx.csv"))
    sc = scans_of(r)
    pg = pd.read_csv(os.path.join(r, "ping_pi.csv")).rename(columns={"t_reply_unix": "t", "rtt_ms": "rtt"})
    tp = rx.t_pub_ns / 1e9
    # first scan fully inside both the message and the ping windows (+-10 s)
    s0, s1 = next((a, b) for a, b in sc if tp.min() < a - 10 and b + 10 < tp.max() and pg.t.min() < a - 10 and b + 10 < pg.t.max())
    w = (tp >= s0 - 10) & (tp <= s1 + 10)
    # ping -D stamps the reply; the request went out rtt earlier
    pg["ts"] = pg.t - pg.rtt / 1e3
    pw = pg[(pg.ts >= s0 - 10) & (pg.ts <= s1 + 10)]
    fig, axs = plt.subplots(2, 1, figsize=(6.5, 3.2), sharex=True, constrained_layout=True)
    for ax in axs:
        ax.axvspan(0, s1 - s0, color="#bdbdbd", alpha=0.35, lw=0, zorder=0)
        ax.set_yscale("log")
        thr20(ax, "y")
    scatter_qos(axs[0], tp[w] - s0, rx.latency_ms[w], 1, s=5, alpha=0.8)
    axs[0].set_ylabel("Latency, QoS 1 (ms)")
    axs[1].scatter(pw.ts - s0, pw.rtt, s=3, color="#555555", lw=0, rasterized=True)
    axs[1].set_ylabel("Ping RTT, 50 Hz (ms)")
    axs[1].set_xlabel("Time from scan start (s)")
    axs[1].set_xlim(-10, s1 - s0 + 10)
    for i, ax in enumerate(axs):
        ax.set_ylim(0.5, 300)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:g}"))
        letter(ax, "ab"[i])
    axs[0].text(0.05, 200, "scan (iw event)", fontsize=7, color=GREY, va="top")
    lw, pw_in = rx.latency_ms[w], pw.rtt
    inside = (tp[w] >= s0) & (tp[w] <= s1)
    print(f"  scan {pd.Timestamp(s0, unit='s', tz='UTC').tz_convert(TZ):%H:%M:%S.%f} - +{s1 - s0:.3f} s")
    print(f"  messages in +-10 s: {len(lw)}; >20 ms: {(lw > 20).sum()} (inside scan {(lw[inside] > 20).sum()}), max {lw.max():.1f} ms")
    print(f"  pings in +-10 s: {len(pw_in)}; >20 ms: {(pw_in > 20).sum()}, max {pw_in.max():.1f} ms; outside scan p50 "
          f"{pw[(pw.ts < s0) | (pw.ts > s1)].rtt.median():.2f} ms")
    save(fig, "fig4_scan_episode")


# ------------------------------------------------------------------ flights
def flight_panels(axs_col, fdir, binpath, day, origin_label, mark_events, t0_kind="arm", show_ylabels=True,
                  rssi_ylim=(-82, -28), dist_ylim=None):
    fs = pd.read_csv(flight_state_csv(binpath))
    # a log can hold several armed intervals (f1b: a short one first); use the one that flew furthest
    fl = fs[fs.kind == "flight"].sort_values("max_dist_m").iloc[-1]
    fs = fs[(fs.kind == "flight") | (fs.flight == fl.flight)]
    t0 = clock_to_unix(fl.arm, day)
    tr = pd.read_csv(os.path.join(fdir, "position", "track.csv"))
    m = pd.read_csv(os.path.join(fdir, "position", "msgs_pos.csv"))
    sd = station(fdir)
    sc = scans_of(fdir)
    t_lo, t_hi = m.t_pub.min() - t0 - 10, m.t_pub.max() - t0 + 10
    a, b, c = axs_col
    trw = tr[(tr.utc - t0 >= t_lo) & (tr.utc - t0 <= t_hi)]
    a.plot(trw.utc - t0, trw.dist_m, color=INK, lw=1.0)
    sdw = sd[(sd.t - t0 >= t_lo) & (sd.t - t0 <= t_hi)]
    b.plot(sdw.t - t0, sdw.signal, color=INK, lw=0.8)
    for q in (0, 1, 2):
        g = m[(m.qos == q) & m.rcvd]
        if len(g):
            scatter_qos(c, g.t_pub - t0, g.latency_ms, q)
    hov = fs[fs.kind == "hover"]
    for _, h in hov.iterrows():
        for ax in axs_col:
            ax.axvspan(clock_to_unix(h.start, day) - t0, clock_to_unix(h.end, day) - t0, color="#e6e6e6", lw=0, zorder=0)
    for s0, s1 in sc:
        for ax in axs_col:
            ax.axvline(s0 - t0, color="#b3261e", lw=0.7, ls=(0, (2, 1)), zorder=2)
        c.annotate("scan", xy=(s0 - t0, 150), xytext=(3, 0), textcoords="offset points", fontsize=7, color="#b3261e", va="center")
    for lab, tt in mark_events:
        for ax in axs_col:
            ax.axvline(tt - t0, color="#444444", lw=0.6, zorder=2)
        a.annotate(lab, xy=(tt - t0, 1.0), xycoords=("data", "axes fraction"), xytext=(2, -2), textcoords="offset points",
                   fontsize=7, color=INK, va="top", ha="left")
    c.set_yscale("log"); c.set_ylim(1, 200)
    c.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:g}"))
    thr20(c, "y")
    b.set_ylim(*rssi_ylim)
    if dist_ylim:
        a.set_ylim(*dist_ylim)
    for ax in axs_col:
        ax.set_xlim(t_lo, t_hi)
    if show_ylabels:
        a.set_ylabel(f"Distance from\n{origin_label} (m)")
        b.set_ylabel("Pi RSSI (dBm)")
        c.set_ylabel("Latency (ms)")
    c.set_xlabel("Time from arming (s)")
    return fs, fl, m, sd, sc, t0, hov


def fig5():
    print("Fig 5: f1b vs time")
    fdir = os.path.join(D, "field_2026-11-22", "f1b")
    binp = os.path.join(D, "field_2026-11-22", "pixhawk", "2026-11-22 16-19-46.bin")
    fig, axs = plt.subplots(3, 1, figsize=(6.5, 4.2), sharex=True, constrained_layout=True,
                            gridspec_kw=dict(height_ratios=[1, 1, 1.4]))
    fs, fl, m, sd, sc, t0, hov = flight_panels(axs, fdir, binp, "2026-11-22", "home", [])
    for i, ax in enumerate(axs):
        letter(ax, "abc"[i])
    for _, h in hov.iterrows():
        axs[0].annotate(f"hover {h.hover_dist_m:g} m", xy=((clock_to_unix(h.start, '2026-11-22') + clock_to_unix(h.end, '2026-11-22')) / 2 - t0, 0.05),
                        xycoords=("data", "axes fraction"), ha="center", va="bottom", fontsize=7, color=GREY)
    legend_qos(axs[2], loc="lower right", marker_only=True, ncol=3)
    for q in (0, 1, 2):
        g = m[m.qos == q]
        print(f"  QoS {q}: sent {len(g)} rcvd {int(g.rcvd.sum())}; {q_stats(g.latency_ms.dropna())}")
    print(f"  max distance {fl.max_dist_m:.1f} m; hovers " + ", ".join(f"{h.hover_dist_m:g} m {h.start}-{h.end}" for _, h in hov.iterrows()))
    print(f"  RSSI {sd.signal.min():.0f}..{sd.signal.max():.0f} dBm (whole log); scans: {len(sc)}")
    save(fig, "fig5_f1b_timeline")


def fig6():
    print("Fig 6: f3 | f4 vs time (distance from the router = f3 home)")
    day = "2026-11-24"
    P = os.path.join(D, "field_2026-11-24", "pixhawk")
    fl_defs = [("F3", "f3", os.path.join(P, "2026-11-24 14-52-25.bin")), ("F4", "f4", os.path.join(P, "2026-11-24 15-26-43.bin"))]
    fig, axs = plt.subplots(3, 2, figsize=(6.5, 4.6), sharex="col", sharey="row", constrained_layout=True,
                            gridspec_kw=dict(height_ratios=[1, 1, 1.4]))
    for j, (lab, name, binp) in enumerate(fl_defs):
        txt = events_txt(binp)
        def ev(pat, after=None):
            for line in txt.splitlines():
                mm = re.match(r"\s*(\d\d:\d\d:\d\d\.\d)\s+(.*)", line)
                if mm and re.search(pat, mm.group(2)):
                    return clock_to_unix(mm.group(1), day)
        rtl, land = ev(r"MODE RTL"), ev(r"EV\s+LAND_COMPLETE$")
        marks = [("RTL", rtl), ("landed", land)]
        loiter = ev(r"MODE Loiter") if name == "f3" else None
        fs, fl, m, sd, sc, t0, hov = flight_panels(axs[:, j], os.path.join(D, "field_2026-11-24", name), binp, day,
                                                   "router", marks, show_ylabels=(j == 0), dist_ylim=(0, 200))
        axs[0, j].annotate(lab, xy=(0.03, 0.9), xycoords="axes fraction", ha="left", va="top", fontsize=8, color=INK)
        for q in (0, 1, 2):
            g = m[m.qos == q]
            print(f"  {lab} QoS {q}: sent {len(g)} rcvd {int(g.rcvd.sum())}; {q_stats(g.latency_ms.dropna())}")
        tr = pd.read_csv(os.path.join(D, "field_2026-11-24", name, "position", "track.csv"))
        print(f"  {lab}: max distance from router {tr.dist_m.max():.1f} m; RTL {pd.Timestamp(rtl, unit='s', tz='UTC').tz_convert(TZ):%H:%M:%S}, "
              f"landed {pd.Timestamp(land, unit='s', tz='UTC').tz_convert(TZ):%H:%M:%S}; RSSI {sd.signal.min():.0f}..{sd.signal.max():.0f} dBm; scans {len(sc)}")
    for i, ax in enumerate(axs.flat):
        letter(ax, "abcdef"[i])
    legend_qos(axs[2, 0], loc="lower left", marker_only=True, ncol=3)
    save(fig, "fig6_f3_f4_timeline")


# ------------------------------------------------------------------ Fig 7
BANDS = [(-55, np.inf, "> -55", -50), (-65, -55, "-65 to -55", -60), (-75, -65, "-75 to -65", -70), (-np.inf, -75, "<= -75", -78)]


def flight_msgs_rssi(fdir, max_gap=1.5):
    """hover/transit messages with nearest station-dump RSSI; +-1 s around scans removed (as link_bands.py)."""
    m = pd.read_csv(os.path.join(fdir, "position", "msgs_pos.csv"))
    sd = station(fdir)
    m = m[m.bin.str.startswith("hover") | (m.bin == "transit")].copy()
    sc = scans_of(fdir)
    keep = np.ones(len(m), bool)
    for s0, s1 in sc:
        keep &= ~((m.t_pub.values >= s0 - 1) & (m.t_pub.values <= s1 + 1))
    m = m[keep]
    i = np.searchsorted(sd.t.values, m.t_pub.values).clip(1, len(sd) - 1)
    j = np.where(np.abs(sd.t.values[i] - m.t_pub.values) < np.abs(sd.t.values[i - 1] - m.t_pub.values), i, i - 1)
    gap = np.abs(sd.t.values[j] - m.t_pub.values)
    m["rssi"] = np.where(gap <= max_gap, sd.signal.values[j], np.nan)
    return m.dropna(subset=["rssi"])


def fig7():
    print("Fig 7: latency vs RSSI, F1-F4 (hover + transit, scans removed)")
    fl = [("F1", os.path.join(D, "field_2026-11-22", "f1b")), ("F2", os.path.join(D, "field_2026-11-23", "f2b")),
          ("F3", os.path.join(D, "field_2026-11-24", "f3")), ("F4", os.path.join(D, "field_2026-11-24", "f4"))]
    fig, axs = plt.subplots(2, 2, figsize=(6.5, 4.6), sharex=True, sharey=True, constrained_layout=True)
    rng = np.random.default_rng(0)
    for k, (lab, fdir) in enumerate(fl):
        ax = axs.flat[k]
        m = flight_msgs_rssi(fdir)
        for q in (0, 1, 2):
            g = m[(m.qos == q) & m.latency_ms.notna()]
            jit = rng.uniform(-0.35, 0.35, len(g))          # RSSI is integer dBm: spread points within +-0.35
            ax.scatter(g.rssi + jit, g.latency_ms, s=2, marker=QOS[q]["marker"], color=QOS[q]["color"], alpha=0.18, lw=0, rasterized=True)
        for q in (0, 1, 2):
            xs, ys, ns = [], [], []
            for lo, hi, name, ctr in BANDS:
                g = m[(m.qos == q) & (m.rssi > lo) & (m.rssi <= hi) & m.latency_ms.notna()]
                if len(g) >= 20:
                    xs.append(ctr); ys.append(g.latency_ms.median()); ns.append((name, len(g), g.latency_ms.median(), 100 * (g.latency_ms > 20).mean()))
            st = QOS[q]
            ax.plot(xs, ys, color=st["color"], ls=st["ls"], marker=st["marker"], ms=5, mec="white", mew=0.6, lw=1.3, zorder=5)
            print(f"  {lab} QoS {q}: n={int((m.qos == q).sum())}; band medians " +
                  "; ".join(f"{nm} n={n} p50={p:.2f} >20={g20:.2f}%" for nm, n, p, g20 in ns))
        ax.annotate(lab, xy=(0.02, 0.97), xycoords="axes fraction", ha="left", va="top", fontsize=8, color=INK)
        thr20(ax, "y")
        letter(ax, "abcd"[k])
    ax = axs[0, 0]
    ax.set_xlim(-80, -30)
    log_ms_axis(ax, "y", 1, 200)
    for ax in axs[1]:
        ax.set_xlabel("Pi RSSI (dBm)")
    for ax in axs[:, 0]:
        ax.set_ylabel("Latency (ms)")
    legend_qos(axs[0, 1], loc="upper right")
    axs[0, 1].text(0.98, 0.04, "large markers: per-band medians (n ≥ 20)", transform=axs[0, 1].transAxes, ha="right", va="bottom", fontsize=7, color=GREY)
    save(fig, "fig7_latency_vs_rssi")


# ------------------------------------------------------------------ Fig 8
def fig8():
    print("Fig 8: bench outage runs (60 s cut)")
    S = os.path.join(D, "bench_outage_2026-11-24")
    runs = [("A_q0_o60", 0, "QoS 0, broker limits 0"), ("A_q1_o60", 1, "QoS 1, broker limits 0"),
            ("A_q2_o60", 2, "QoS 2, broker limits 0"), ("B_q2_o60", 2, "QoS 2, broker defaults")]
    fig, axs = plt.subplots(2, 2, figsize=(6.5, 4.2), sharex=True, sharey=True, layout="constrained")
    for k, (run, q, lab) in enumerate(runs):
        ax = axs.flat[k]
        r = os.path.join(S, run)
        o = json.load(open(os.path.join(r, "outage.json")))
        t_on, t_off = o["events"]["t_on"], o["events"]["t_off"]
        seg = pd.read_csv(os.path.join(r, "segments.csv")).iloc[0]
        pl = pd.read_csv(os.path.join(r, "sent.csv"))
        rx = pd.read_csv(os.path.join(r, "rx_all.csv")).sort_values("t_rx_ns").drop_duplicates(["topic", "t_pub_ns"])
        mm = pl.merge(rx[["topic", "t_pub_ns", "latency_ms"]], on=["topic", "t_pub_ns"], how="left")
        x = mm.t_pub_ns / 1e9 - t_on
        ok = mm.latency_ms.notna()
        ax.axvspan(0, t_off - t_on, color="#bdbdbd", alpha=0.35, lw=0, zorder=0)
        st = QOS[q]
        ax.scatter(x[ok], mm.latency_ms[ok] / 1e3, s=3, marker=st["marker"], color=st["color"], alpha=0.6, lw=0, rasterized=True)
        lost = x[~ok]
        if len(lost):
            ax.plot(lost, np.full(len(lost), 1.035), "|", color="#b3261e", ms=4, mew=0.3, alpha=0.5, transform=ax.get_xaxis_transform(), clip_on=False)
            ax.annotate("lost", xy=(lost.min(), 1.035), xycoords=("data", "axes fraction"), xytext=(-3, 0), textcoords="offset points",
                        ha="right", va="center", fontsize=7, color="#b3261e")
        ax.axhline(0.020, color=GREY, lw=0.6, ls=":", zorder=1)
        n_ok, n = int(ok.sum()), len(mm)
        ax.annotate(f"{lab}\ndelivered {n_ok} / {n}", xy=(0.98, 0.84), xycoords="axes fraction", ha="right", va="top", fontsize=7, color=INK)
        letter(ax, "abcd"[k])
        dur = mm[(x >= 0) & (x < t_off - t_on)]
        print(f"  {run}: delivered {n_ok}/{n}, lost {n - n_ok} (during cut {int(dur.latency_ms.isna().sum())}/{len(dur)}); "
              f"max latency {mm.latency_ms.max() / 1e3:.2f} s; cut {t_off - t_on:.2f} s")
    ax = axs[0, 0]
    ax.set_yscale("log"); ax.set_ylim(1e-3, 100)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:g}"))
    ax.set_xlim(-32, 150)
    for ax in axs[1]:
        ax.set_xlabel("Publish time relative to the cut (s)")
    for ax in axs[:, 0]:
        ax.set_ylabel("Latency (s)")
    for ax in axs.flat:
        ax.text(30, 0.3, "cut", fontsize=7, color=GREY, ha="center")
    from matplotlib.lines import Line2D
    fig.legend(handles=[Line2D([], [], ls="none", marker=QOS[q]["marker"], color=QOS[q]["color"], ms=4, label=QOS[q]["label"]) for q in (0, 1, 2)]
               + [Line2D([], [], ls="none", marker="|", color="#b3261e", ms=6, label="lost (rug above panel)")],
               loc="outside upper center", ncol=4)
    save(fig, "fig8_bench_outage")


FIGS = {"2": fig2, "3": fig3, "4": fig4, "5": fig5, "6": fig6, "7": fig7, "8": fig8}

if __name__ == "__main__":
    for k in (sys.argv[1:] or list(FIGS)):
        FIGS[k]()
