# Metrics: `fix_bssid`

1 runs. Latency = laptop receive - Pi publish (first arrival). Jitter = std of latency. PDR from unique (topic, seq) in pi_log.csv vs rx.csv. Aggregate rate (Eq. 8) R = sum f_k S_k x 8, S_k = mean payload bytes (payload only): nominal = publisher rates (as in the abstract's Table 2), measured = received update rates. AoI from t_sample_ns at the laptop; pooled AoI = duration-weighted mean of run averages, peak = max over runs.

## Clock check

No run flagged (chrony LastRx <= 60 s and |offset| <= 1 ms after the run, and during it where side logging recorded chrony).

## Delivery and latency (pooled, ms)

| group | qos | runs | sent | received | pdr_pct | plr_pct | lat_mean_ms | lat_jitter_ms | lat_p50_ms | lat_p95_ms | lat_p99_ms | lat_max_ms | lat_over20_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos | 1 | 1 | 43200 | 43200 | 100.000 | 0.000 | 1.86 | 0.40 | 1.84 | 2.35 | 2.86 | 34.32 | 0.005 |

## Latency without scan windows (ms; messages published within 1 s of an `iw event` scan removed)

| group | qos | scans | msgs_in_scan | noscan_lat_mean_ms | noscan_lat_jitter_ms | noscan_lat_p50_ms | noscan_lat_p95_ms | noscan_lat_p99_ms | noscan_lat_max_ms | noscan_lat_over20_pct |
|---|---|---|---|---|---|---|---|---|---|---|
| qos | 1 | 0 | 0 | 1.86 | 0.40 | 1.84 | 2.35 | 2.86 | 34.32 | 0.005 |

## Rates, payload, link

| group | qos | msgs_per_s | payload_kbps | agg_rate_nominal_kbps | agg_rate_measured_kbps | bmp280_rate_hz | bmp280_bytes | ina219_rate_hz | ina219_bytes | mpu6050_rate_hz | mpu6050_bytes | rssi_mean_dbm | rssi_min_dbm | scans | scan_time_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos | 1 | 24.00 | 53.07 | 53.06 | 53.07 | 2.00 | 198.06 | 2.00 | 202.25 | 20.00 | 291.62 | -42.1 | -48 | 0 | 0.00 |

## Age of Information (ms)

| group | qos | bmp280_aoi_avg_ms | bmp280_paoi_mean_ms | bmp280_paoi_max_ms | ina219_aoi_avg_ms | ina219_paoi_mean_ms | ina219_paoi_max_ms | mpu6050_aoi_avg_ms | mpu6050_paoi_mean_ms | mpu6050_paoi_max_ms |
|---|---|---|---|---|---|---|---|---|---|---|
| qos | 1 | 252.04 | 502.04 | 505.55 | 251.70 | 501.70 | 511.17 | 26.89 | 51.86 | 84.34 |

## Per run

| run | qos | duration_s | sent | received | pdr_pct | lat_mean_ms | lat_jitter_ms | lat_p50_ms | lat_p95_ms | lat_p99_ms | lat_max_ms | lat_over20_pct | agg_rate_measured_kbps | mpu6050_aoi_avg_ms | mpu6050_paoi_max_ms | rssi_mean_dbm | scans | scan_time_pct | clk_after_offset_ms | clk_log_max_lastrx_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos1_rep1 | 1 | 1800 | 43200 | 43200 | 100.000 | 1.86 | 0.40 | 1.84 | 2.35 | 2.86 | 34.32 | 0.005 | 53.07 | 26.89 | 84.34 | -42.1 | 0 | 0.00 | -0.01 |  |
