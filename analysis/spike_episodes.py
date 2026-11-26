#!/usr/bin/env python3
"""Find and describe latency spike episodes in one or more campaigns.

Episode: >= MIN_N messages over THRESH_MS whose publish times are less than GAP_S apart.
In QoS 2 runs where the broker had Nagle on (holds of ~51-66 ms on ina219 and some lone IMU
messages), detection uses NAGLE_THRESH_MS instead (--skip-ina-qos2 CAMPAIGN, repeatable).

For every episode it reports:
  - timing relative to the run start (meta start_unix = just before the publisher is launched
    over SSH) and to the first published sample;
  - Pi-side lateness: sched_lag_ms of the publisher loop and IMU sample spacing, inside the
    episode and in the 5 s before it (t_pub_ns - t_sample_ns is not useful: both are taken
    back to back after the sensor read);
  - "holds": groups of delayed messages released together (t_rx gaps < RELEASE_GAP_MS).
    Hold length ~ max latency in the group; slope of latency vs t_pub (-1 = held then
    released at once);
  - wall-clock times, intervals, and a period test (Monte Carlo against uniform times
    inside the observed run windows).
Writes data/<campaign>/episodes/*.png and episodes.csv; prints the tables.

Usage: python analysis/spike_episodes.py base20 base20_nd --skip-ina-qos2 base20
"""
import argparse, glob, json, os, re
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

THRESH_MS, MIN_N, GAP_S, RELEASE_GAP_MS = 20.0, 10, 1.0, 3.0
NAGLE_THRESH_MS = 70.0
HOME = os.path.expanduser("~/uav-mqtt/data")

ap = argparse.ArgumentParser()
ap.add_argument("campaigns", nargs="+")
ap.add_argument("--skip-ina-qos2", action="append", default=[])
ap.add_argument("--period", type=float, default=300.0)
a = ap.parse_args()

def grab(path, pat):
    try:
        m = re.search(pat, open(path).read())
        return float(m.group(1)) if m else np.nan
    except OSError:
        return np.nan

def wifi(path):
    return {k: grab(path, p) for k, p in [
        ("sig", r"signal:\s*(-?\d+)"), ("txr", r"tx bitrate:\s*([\d.]+)"),
        ("rxr", r"rx bitrate:\s*([\d.]+)"), ("rxb", r"RX:\s*(\d+) bytes"),
        ("rxp", r"RX:.*\((\d+) packets"), ("txb", r"TX:\s*(\d+) bytes"),
        ("txp", r"TX:.*\((\d+) packets")]}

def chrony(path):
    return {k: grab(path, p) for k, p in [
        ("rms_ms", r"RMS offset\s*:\s*([\d.]+)"), ("last_ms", r"Last offset\s*:\s*([-\d.]+)"),
        ("skew", r"Skew\s*:\s*([\d.]+)"), ("rootdelay_ms", r"Root delay\s*:\s*([\d.]+)"),
        ("upd_s", r"Update interval\s*:\s*([\d.]+)")]}

runs, eps = [], []
for camp in a.campaigns:
    odir = f"{HOME}/{camp}/episodes"
    os.makedirs(odir, exist_ok=True)
    for rdir in sorted(glob.glob(f"{HOME}/{camp}/qos*_rep*")):
        run = os.path.basename(rdir)
        meta = json.load(open(f"{rdir}/meta.json"))
        rx = pd.read_csv(f"{rdir}/rx.csv").drop_duplicates(["topic", "seq"])
        pl = pd.read_csv(f"{rdir}/pi_log.csv", usecols=["topic", "seq", "t_sample_ns", "t_pub_ns", "sched_lag_ms"])
        df = pl.merge(rx[["topic", "seq", "t_rx_ns", "latency_ms", "dup"]], on=["topic", "seq"], how="left")
        df = df.sort_values("t_pub_ns").reset_index(drop=True)
        t_start = meta["start_unix"]
        t0 = df["t_pub_ns"].iloc[0] / 1e9
        t_end = df["t_pub_ns"].iloc[-1] / 1e9
        df["t"] = df["t_pub_ns"] / 1e9 - t0               # run time of publish, s
        df["sensor"] = df["topic"].str.split("/").str[-1]
        wb, wa = wifi(f"{rdir}/wifi_before.txt"), wifi(f"{rdir}/wifi_after.txt")
        cb, ca = chrony(f"{rdir}/chrony_before.txt"), chrony(f"{rdir}/chrony_after.txt")
        det = df[df["latency_ms"] > THRESH_MS]
        if meta["qos"] == 2 and camp in a.skip_ina_qos2:
            # broker Nagle holds (ina219 and ~6% of lone IMU) reach ~66 ms: detect above that
            det = df[df["latency_ms"] > NAGLE_THRESH_MS]
        groups = []
        if len(det):
            gid = (det["t"].diff() > GAP_S).cumsum()
            groups = [g for _, g in det.groupby(gid) if len(g) >= MIN_N]
        runs.append(dict(camp=camp, run=run, qos=meta["qos"], start=t_start, t0=t0, t_end=t_end,
                         startup_s=t0 - t_start, n_ep=len(groups),
                         dup=int(df["dup"].fillna(0).sum()), lost=int(df["latency_ms"].isna().sum()),
                         lag_max=df["sched_lag_ms"].max(), lag_p99=df["sched_lag_ms"].quantile(.99),
                         **{f"{k}_b": v for k, v in wb.items()}, **{f"{k}_a": v for k, v in wa.items()},
                         **{f"c_{k}_b": v for k, v in cb.items()}, **{f"c_{k}_a": v for k, v in ca.items()}))
        for i, g in enumerate(groups):
            ts, te = g["t"].min(), g["t"].max()
            win = df[(df["t"] >= ts - 0.2) & (df["t"] <= te + 0.2)]
            pre = df[(df["t"] >= ts - 5) & (df["t"] < ts - 0.2)]
            imu_w = win[win["sensor"] == "mpu6050"]["t_sample_ns"].diff().dropna() / 1e6
            # holds: delayed messages released together (by t_rx)
            d = win[win["latency_ms"] > THRESH_MS].sort_values("t_rx_ns")
            rel = (d["t_rx_ns"].diff() / 1e6 > RELEASE_GAP_MS).cumsum()
            holds = []
            for _, h in d.groupby(rel):
                slope = np.polyfit(h["t"], h["latency_ms"] / 1e3, 1)[0] if len(h) >= 3 else np.nan
                holds.append(dict(t=h["t"].min(), n=len(h), len_ms=h["latency_ms"].max(),
                                  rx_spread_ms=(h["t_rx_ns"].max() - h["t_rx_ns"].min()) / 1e6,
                                  slope=slope, sensors="".join(sorted(set(h["sensor"].str[0])))))
            H = pd.DataFrame(holds)
            hs = H["t"].values
            eps.append(dict(
                camp=camp, run=run, qos=meta["qos"], ep=i,
                wall=t0 + ts, t_from_start=t0 + ts - t_start, t_run=ts, dur_s=te - ts,
                n_over=len(g), n_win=len(win), max_ms=g["latency_ms"].max(),
                p50_in_ms=g["latency_ms"].median(),
                sensors=",".join(f"{s}:{(g['sensor'] == s).sum()}" for s in ["bmp280", "mpu6050", "ina219"]),
                lag_max_in=win["sched_lag_ms"].max(), lag_max_pre=pre["sched_lag_ms"].max(),
                imu_dt_max_in=imu_w.max(), imu_dt_min_in=imu_w.min(),
                n_holds=len(H), hold_ms=",".join(f"{x:.0f}" for x in H["len_ms"]),
                hold_gap_s=",".join(f"{x:.2f}" for x in np.diff(hs)),
                hold_slope_med=H["slope"].median(), rx_spread_med_ms=H["rx_spread_ms"].median(),
                lat_before_ms=pre["latency_ms"].median(),
            ))
            # plot
            fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
            w2 = df[(df["t"] >= ts - 2) & (df["t"] <= te + 2)]
            for s, m in [("bmp280", "s"), ("mpu6050", "o"), ("ina219", "^")]:
                ws = w2[w2["sensor"] == s]
                ax[0].plot(ws["t"], ws["latency_ms"], m, ms=3, label=s)
                ax[1].plot(ws["t"], (ws["t_rx_ns"] / 1e9 - t0), m, ms=3)
            ax[0].set_ylabel("latency, ms"); ax[0].legend(); ax[0].axhline(THRESH_MS, lw=.5, c="k")
            ax[1].plot([ts - 2, te + 2], [ts - 2, te + 2], "k-", lw=.5)
            ax[1].set_ylabel("receive time, s"); ax[1].set_xlabel("publish time from first sample, s")
            ax[0].set_title(f"{camp} {run} episode {i}: {len(g)} msgs over {THRESH_MS:.0f} ms, max {g['latency_ms'].max():.0f} ms")
            fig.tight_layout(); fig.savefig(f"{odir}/{run}_ep{i}.png", dpi=110); plt.close(fig)

R, E = pd.DataFrame(runs), pd.DataFrame(eps)
pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_colwidth", 60)
for camp in a.campaigns:
    E[E["camp"] == camp].to_csv(f"{HOME}/{camp}/episodes/episodes.csv", index=False)

print("=== Episodes ===")
print(E[["camp", "run", "t_from_start", "t_run", "dur_s", "n_over", "n_win", "max_ms", "p50_in_ms",
         "sensors", "lat_before_ms"]].round(2).to_string(index=False))
print("\n=== Pi side (ms) ===")
print(E[["run", "lag_max_in", "lag_max_pre", "imu_dt_min_in", "imu_dt_max_in"]].round(2).to_string(index=False))
print("\n=== Holds ===")
print(E[["run", "n_holds", "hold_slope_med", "rx_spread_med_ms", "hold_ms", "hold_gap_s"]].round(2).to_string(index=False))
print("\n=== Run-level: lag, dup, loss, startup ===")
print(R[["camp", "run", "n_ep", "startup_s", "lag_max", "lag_p99", "dup", "lost"]].round(3).to_string(index=False))

# Wi-Fi / chrony per run, with/without episodes
R["rxp_d"], R["txp_d"] = R["rxp_a"] - R["rxp_b"], R["txp_a"] - R["txp_b"]
R["rxb_d"], R["txb_d"] = R["rxb_a"] - R["rxb_b"], R["txb_a"] - R["txb_b"]
for k in ["c_rms_ms", "c_last_ms", "c_rootdelay_ms"]:
    for s in ["_b", "_a"]:
        R[k + s] *= 1000
cols = ["sig_b", "sig_a", "txr_b", "txr_a", "rxr_b", "rxr_a", "rxp_d", "txp_d", "rxb_d", "txb_d",
        "c_rms_ms_b", "c_rms_ms_a", "c_last_ms_a", "c_skew_a", "c_rootdelay_ms_a", "c_upd_s_a"]
print("\n=== Wi-Fi / chrony per run ===")
print(R[["camp", "run", "n_ep"] + cols].round(3).to_string(index=False))
print("\n=== Means by episode / no episode ===")
print(R.groupby(R["n_ep"] > 0)[cols].mean().round(3).T.to_string())

# Wall-clock timing
print("\n=== Wall clock ===")
for camp in a.campaigns:
    Rc, Ec = R[R["camp"] == camp], E[E["camp"] == camp].sort_values("wall")
    span0, span1 = Rc["t0"].min(), Rc["t_end"].max()
    cov = (Rc["t_end"] - Rc["t0"]).sum() / (span1 - span0)
    print(f"{camp}: span {span1 - span0:.0f} s, run coverage {100 * cov:.1f}%, episodes {len(Ec)}")
    for _, e in Ec.iterrows():
        print(f"  {pd.Timestamp(e['wall'], unit='s', tz='UTC').tz_convert('America/Denver'):%H:%M:%S.%f}"[:-3]
              + f"  {e['run']}  t_run {e['t_run']:.2f} s")
    iv = np.diff(Ec["wall"].values)
    if len(iv):
        print("  intervals s:", ", ".join(f"{x:.1f}" for x in iv),
              "| / period:", ", ".join(f"{x / a.period:.3f}" for x in iv))

# Period test: phase concentration (Rayleigh R) of episode times mod P within each campaign,
# vs Monte Carlo of the same number of events placed uniformly in the observed run windows.
# Phases are aligned per campaign (no assumption of phase lock across the 2.5 h gap).
rng = np.random.default_rng(1)
def rbar(times_by_camp, P):
    # mean resultant length after removing each campaign's own mean phase, pooled
    z = []
    for t in times_by_camp:
        if len(t) < 2:
            continue
        ph = np.exp(2j * np.pi * np.asarray(t) / P)
        z.append(ph * np.conj(ph.mean() / abs(ph.mean())) if abs(ph.mean()) > 0 else ph)
    z = np.concatenate(z)
    return abs(z.mean()), len(z)
def sample(camp, n):
    Rc = R[R["camp"] == camp]
    L = (Rc["t_end"] - Rc["t0"]).values
    idx = rng.choice(len(Rc), n, p=L / L.sum())
    return Rc["t0"].values[idx] + rng.random(n) * L[idx]
obs_t = [E[E["camp"] == c]["wall"].values for c in a.campaigns]
Ps = np.arange(60, 900.5, 1.0)
print(f"\n=== Period test (Monte Carlo, 2000 draws, uniform in observed windows) ===")
for P in [a.period, 290, 295, 305, 310]:
    r, n = rbar(obs_t, P)
    null = [rbar([sample(c, len(t)) for c, t in zip(a.campaigns, obs_t)], P)[0] for _ in range(2000)]
    print(f"P={P:.0f} s: R={r:.3f} (n={n}), p={np.mean(np.array(null) >= r):.3f}")
# scan over periods, with Monte Carlo correction for the scan (max over P)
scan = np.array([rbar(obs_t, P)[0] for P in Ps])
best = Ps[np.argmax(scan)]
null_max = []
for _ in range(300):
    st = [sample(c, len(t)) for c, t in zip(a.campaigns, obs_t)]
    null_max.append(max(rbar(st, P)[0] for P in Ps[::2]))
print(f"Best period in 60-900 s: {best:.0f} s, R={scan.max():.3f}; "
      f"p (corrected for scanning) = {np.mean(np.array(null_max) >= scan.max()):.3f}")
print("Top periods:", ", ".join(f"{Ps[i]:.0f}({scan[i]:.2f})" for i in np.argsort(scan)[::-1][:8]))

# Predicted times for a strict P-s period anchored on each campaign's first episode:
# where do they land (inside a run without an episode = evidence against strict period)?
print(f"\n=== Strict {a.period:.0f} s grid anchored on first episode (and least-squares fit) ===")
for camp, t in zip(a.campaigns, obs_t):
    if len(t) == 0:
        continue
    Rc = R[R["camp"] == camp]
    k = np.round((t - t[0]) / a.period)
    if len(t) >= 2:
        A = np.vstack([np.ones_like(k), k]).T
        (b0, Pfit), res, *_ = np.linalg.lstsq(A, t, rcond=None)
        resid = t - (b0 + Pfit * k)
        print(f"{camp}: fitted period {Pfit:.1f} s, residuals s: " + ", ".join(f"{x:+.1f}" for x in resid))
    for kk in range(int(np.floor((Rc["t0"].min() - t[0]) / a.period)), int(np.ceil((Rc["t_end"].max() - t[0]) / a.period)) + 1):
        tp = t[0] + kk * a.period
        inrun = Rc[(Rc["t0"] <= tp) & (Rc["t_end"] >= tp)]
        hit = np.any(np.abs(t - tp) < 15)
        where = f"{inrun['run'].iloc[0]} t_run {tp - inrun['t0'].iloc[0]:.1f} s (episodes in run: {inrun['n_ep'].iloc[0]})" if len(inrun) else "between runs"
        print(f"  k={kk:+d}: {where}{'  <- episode within 15 s' if hit else ''}")

# Pooled fit across all campaigns: one period and phase, integer cycle numbers.
# Then predict, for every run of every campaign given, whether an episode should start
# inside it, and compare with what was detected.
t_all = np.sort(E["wall"].values)
if len(t_all) >= 3:
    P = a.period
    for _ in range(5):                       # refine: assign cycles, refit
        k = np.round((t_all - t_all[0]) / P)
        A = np.vstack([np.ones_like(k), k]).T
        (b0, P), *_ = np.linalg.lstsq(A, t_all, rcond=None)
    k = np.round((t_all - t_all[0]) / P)
    resid = t_all - (b0 + P * k)
    print(f"\n=== Pooled fit over all {len(t_all)} episodes: period {P:.3f} s, cycles {int(k[0])}..{int(k[-1])}, "
          f"residuals s: " + ", ".join(f"{x:+.2f}" for x in resid))
    print("Prediction per run (episode start predicted inside the run's publish window?):")
    hits = {"pred_yes_obs_yes": 0, "pred_yes_obs_no": 0, "pred_no_obs_yes": 0, "pred_no_obs_no": 0}
    for _, r in R.sort_values("t0").iterrows():
        kk = np.arange(np.ceil((r["t0"] - b0) / P), np.floor((r["t_end"] - b0) / P) + 1)
        pred = [b0 + P * x - r["t0"] for x in kk]
        obs = E[(E["camp"] == r["camp"]) & (E["run"] == r["run"])]["t_run"].values
        key = f"pred_{'yes' if pred else 'no'}_obs_{'yes' if len(obs) else 'no'}"
        hits[key] += 1
        if pred or len(obs):
            print(f"  {r['camp']:>10} {r['run']}: predicted t_run {', '.join(f'{x:.2f}' for x in pred) or '-'}"
                  f" | observed {', '.join(f'{x:.2f}' for x in obs) or '-'}")
    print("  ", hits)
