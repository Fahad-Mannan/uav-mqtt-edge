# Metrics: `q0_nd_ab`

10 runs. Latency = laptop receive - Pi publish (first arrival). Jitter = std of latency. PDR from unique (topic, seq) in pi_log.csv vs rx.csv. Aggregate rate (Eq. 8) R = sum f_k S_k x 8, S_k = mean payload bytes (payload only): nominal = publisher rates (as in the abstract's Table 2), measured = received update rates. AoI from t_sample_ns at the laptop; pooled AoI = duration-weighted mean of run averages, peak = max over runs.

## Clock check

No run flagged (chrony LastRx <= 60 s and |offset| <= 1 ms after the run, and during it where side logging recorded chrony).

## Delivery and latency (pooled, ms)

| group | qos | nodelay | runs | sent | received | pdr_pct | plr_pct | lat_mean_ms | lat_jitter_ms | lat_p50_ms | lat_p95_ms | lat_p99_ms | lat_max_ms | lat_over20_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos | 0 |  | 10 | 14400 | 14400 | 100.000 | 0.000 | 2.35 | 6.87 | 1.67 | 2.27 | 25.51 | 122.58 | 1.069 |
| condition | 0 | 0 | 5 | 7200 | 7200 | 100.000 | 0.000 | 3.00 | 9.67 | 1.67 | 2.36 | 59.53 | 122.58 | 2.139 |
| condition | 0 | 1 | 5 | 7200 | 7200 | 100.000 | 0.000 | 1.69 | 0.36 | 1.68 | 2.21 | 3.05 | 5.17 | 0.000 |

## Latency without scan windows (ms; messages published within 1 s of an `iw event` scan removed)

| group | qos | nodelay | scans | msgs_in_scan | noscan_lat_mean_ms | noscan_lat_jitter_ms | noscan_lat_p50_ms | noscan_lat_p95_ms | noscan_lat_p99_ms | noscan_lat_max_ms | noscan_lat_over20_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qos | 0 |  | 3 | 408 | 1.72 | 1.27 | 1.67 | 2.20 | 2.89 | 44.42 | 0.107 |
| condition | 0 | 0 | 3 | 408 | 1.74 | 1.78 | 1.66 | 2.18 | 2.68 | 44.42 | 0.221 |
| condition | 0 | 1 | 0 | 0 | 1.69 | 0.36 | 1.68 | 2.21 | 3.05 | 5.17 | 0.000 |

## Rates, payload, link

| group | qos | msgs_per_s | payload_kbps | agg_rate_nominal_kbps | agg_rate_measured_kbps | bmp280_rate_hz | bmp280_bytes | ina219_rate_hz | ina219_bytes | mpu6050_rate_hz | mpu6050_bytes | rssi_mean_dbm | rssi_min_dbm | scans | scan_time_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos | 0 | 24.02 | 52.79 | 52.75 | 52.79 | 2.00 | 196.28 | 2.00 | 200.42 | 20.02 | 290.00 | -42.2 | -45 | 3 | 1.86 |
| condition | 0 | 24.02 | 52.79 | 52.74 | 52.79 | 2.00 | 196.30 | 2.00 | 200.33 | 20.02 | 289.99 | -42.1 | -45 | 3 | 3.72 |
| condition | 0 | 24.02 | 52.79 | 52.75 | 52.79 | 2.00 | 196.27 | 2.00 | 200.50 | 20.02 | 290.01 | -42.2 | -45 | 0 | 0.00 |

## Age of Information (ms)

| group | qos | bmp280_aoi_avg_ms | bmp280_paoi_mean_ms | bmp280_paoi_max_ms | ina219_aoi_avg_ms | ina219_paoi_mean_ms | ina219_paoi_max_ms | mpu6050_aoi_avg_ms | mpu6050_paoi_mean_ms | mpu6050_paoi_max_ms |
|---|---|---|---|---|---|---|---|---|---|---|
| qos | 0 | 252.32 | 502.32 | 616.54 | 252.08 | 502.01 | 611.46 | 27.38 | 52.36 | 172.69 |
| condition | 0 | 252.76 | 502.75 | 616.54 | 252.74 | 502.60 | 611.46 | 28.04 | 53.02 | 172.69 |
| condition | 0 | 251.89 | 501.89 | 503.83 | 251.43 | 501.43 | 504.92 | 26.72 | 51.71 | 61.09 |

## Per run

| run | qos | duration_s | sent | received | pdr_pct | lat_mean_ms | lat_jitter_ms | lat_p50_ms | lat_p95_ms | lat_p99_ms | lat_max_ms | lat_over20_pct | agg_rate_measured_kbps | mpu6050_aoi_avg_ms | mpu6050_paoi_max_ms | rssi_mean_dbm | scans | scan_time_pct | clk_after_offset_ms | clk_log_max_lastrx_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos0_nd0_rep1 | 0 | 60 | 1440 | 1440 | 100.000 | 3.99 | 13.38 | 1.61 | 2.47 | 85.25 | 122.58 | 3.542 | 52.77 | 28.89 | 172.69 | -42.2 | 1 | 6.20 | 0.02 |  |
| qos0_nd0_rep2 | 0 | 60 | 1440 | 1440 | 100.000 | 1.45 | 1.70 | 1.33 | 1.91 | 2.34 | 40.25 | 0.208 | 52.81 | 26.39 | 59.52 | -42.4 | 0 | 0.00 | 0.02 |  |
| qos0_nd0_rep3 | 0 | 60 | 1440 | 1440 | 100.000 | 3.78 | 11.61 | 1.71 | 2.71 | 76.62 | 120.78 | 3.403 | 52.78 | 28.96 | 168.27 | -42.0 | 1 | 6.20 | -0.00 |  |
| qos0_nd0_rep4 | 0 | 60 | 1440 | 1440 | 100.000 | 1.93 | 1.74 | 1.84 | 2.34 | 2.86 | 43.08 | 0.208 | 52.79 | 26.89 | 59.68 | -42.0 | 0 | 0.00 | -0.02 |  |
| qos0_nd0_rep5 | 0 | 60 | 1440 | 1440 | 100.000 | 3.86 | 11.90 | 1.74 | 3.07 | 77.17 | 122.21 | 3.333 | 52.78 | 29.07 | 172.34 | -42.1 | 1 | 6.21 | 0.02 |  |
| qos0_nd1_rep1 | 0 | 60 | 1440 | 1440 | 100.000 | 1.61 | 0.31 | 1.59 | 2.04 | 2.46 | 4.84 | 0.000 | 52.82 | 26.64 | 61.09 | -42.0 | 0 | 0.00 | 0.00 |  |
| qos0_nd1_rep2 | 0 | 60 | 1440 | 1440 | 100.000 | 1.84 | 0.35 | 1.80 | 2.41 | 3.09 | 5.17 | 0.000 | 52.80 | 26.89 | 59.75 | -42.6 | 0 | 0.00 | -0.01 |  |
| qos0_nd1_rep3 | 0 | 60 | 1440 | 1440 | 100.000 | 1.87 | 0.33 | 1.84 | 2.27 | 3.36 | 4.34 | 0.000 | 52.80 | 26.91 | 59.44 | -42.1 | 0 | 0.00 | 0.01 |  |
| qos0_nd1_rep4 | 0 | 60 | 1440 | 1440 | 100.000 | 1.51 | 0.39 | 1.40 | 2.07 | 3.29 | 4.65 | 0.000 | 52.81 | 26.51 | 59.66 | -41.9 | 0 | 0.00 | 0.02 |  |
| qos0_nd1_rep5 | 0 | 60 | 1440 | 1440 | 100.000 | 1.65 | 0.30 | 1.63 | 2.10 | 2.54 | 4.57 | 0.000 | 52.74 | 26.68 | 59.50 | -42.4 | 0 | 0.00 | -0.02 |  |
