#!/usr/bin/env bash
# Pi-side event logging during a run (no sudo, read-only; changes no settings).
# Usage: side_log.sh OUTDIR [STATION_DUMP_INTERVAL_S (0 = off, default 0.5)] [MAX_S (0 = no limit)]
# Start detached with setsid; stop by killing the process group (kill -TERM -- -PID), or let
# it stop itself after MAX_S seconds (field runs: the laptop may not reach the Pi at the end).
# All timestamps are Unix wall time (chrony keeps the Pi within ~1 ms of the laptop).
set -u
OUT=$1
SD=${2:-0.5}
MAX=${3:-0}
mkdir -p "$OUT"
IW=/usr/sbin/iw
IFP=/fi/w1/wpa_supplicant1/Interfaces/0

trap 'kill $(jobs -p) 2>/dev/null; wait; echo "stop_unix $(date +%s.%N)" >> "$OUT/header.txt"; exit 0' TERM INT
if [ "$MAX" != "0" ]; then
  (sleep "$MAX"; kill -TERM $$) &
fi

{
  echo "start_unix $(date +%s.%N)"
  echo "uptime $(cat /proc/uptime)"
  echo "station_dump_interval_s $SD"
  echo "max_s $MAX"
  echo "power_save $($IW dev wlan0 get power_save)"
  # only the bgscan key is extracted (the network properties also hold key material)
  busctl --json=short get-property fi.w1.wpa_supplicant1 $IFP/Networks/0 fi.w1.wpa_supplicant1.Network Properties 2>/dev/null \
    | python3 -c 'import json,sys; print("bgscan", json.load(sys.stdin)["data"].get("bgscan", {}).get("data"))' 2>/dev/null \
    || echo "bgscan: not read"
} > "$OUT/header.txt"

# nl80211 events: scan started/finished/aborted, disconnects, channel switches
$IW event -t > "$OUT/iw_event.log" 2>&1 &

# NetworkManager / wpa_supplicant and kernel messages
journalctl -f -n 0 -o short-unix -u NetworkManager -u wpa_supplicant > "$OUT/journal_net.log" 2>&1 &
journalctl -f -n 0 -k -o short-unix > "$OUT/journal_kernel.log" 2>&1 &

# wpa_supplicant BSS table every 5 s: Age (s since last seen in a scan) dates each scan
# completion to within ~1 s, as a check on iw event (polled slowly: busctl costs CPU)
(while :; do
   t=$(date +%s.%N)
   for B in $(busctl get-property fi.w1.wpa_supplicant1 $IFP fi.w1.wpa_supplicant1.Interface BSSs 2>/dev/null | grep -o '/fi[^"]*'); do
     echo "$t $B $(busctl get-property fi.w1.wpa_supplicant1 $B fi.w1.wpa_supplicant1.BSS Frequency Signal Age 2>/dev/null | tr '\n' ' ')"
   done
   sleep 5
 done) > "$OUT/bss_age.log" 2>&1 &

# Station counters (tx failed, signal, bitrates)
if [ "$SD" != "0" ]; then
  (while :; do echo "T $(date +%s.%N)"; $IW dev wlan0 station dump; sleep "$SD"; done) > "$OUT/station_dump.log" 2>&1 &
fi

# Clock health every 10 s: chrony's view of the laptop (LastRx, reach) and the current offset,
# so a stall during a link loss can be dated
(while :; do
   echo "$(date +%s.%N) $(chronyc -n sources 2>&1 | grep ' 192.168.1.4 ') | $(chronyc tracking 2>&1 | grep 'System time')"
   sleep 10
 done) > "$OUT/chrony.log" 2>&1 &

# Throttling, temperature, ARM clock, load, CPU counters
(while :; do
   echo "$(date +%s.%N) $(vcgencmd get_throttled) $(vcgencmd measure_temp) $(vcgencmd measure_clock arm) load $(cut -d' ' -f1-3 /proc/loadavg) $(head -1 /proc/stat)"
   sleep 1
 done) > "$OUT/system.log" 2>&1 &

wait
