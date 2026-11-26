# Metrics: `base_final`

15 runs. Latency = laptop receive - Pi publish (first arrival). Jitter = std of latency. PDR from unique (topic, seq) in pi_log.csv vs rx.csv. Aggregate rate (Eq. 8) R = sum f_k S_k x 8, S_k = mean payload bytes (payload only): nominal = publisher rates (as in the abstract's Table 2), measured = received update rates. AoI from t_sample_ns at the laptop; pooled AoI = duration-weighted mean of run averages, peak = max over runs.

## Clock check

No run flagged (chrony LastRx <= 60 s and |offset| <= 1 ms after the run, and during it where side logging recorded chrony).

## Delivery and latency (pooled, ms)

| group | qos | runs | sent | received | pdr_pct | plr_pct | lat_mean_ms | lat_jitter_ms | lat_p50_ms | lat_p95_ms | lat_p99_ms | lat_max_ms | lat_over20_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos | 0 | 5 | 7200 | 7200 | 100.000 | 0.000 | 5.27 | 6.07 | 5.35 | 6.11 | 7.44 | 128.86 | 0.750 |
| qos | 1 | 5 | 7200 | 7200 | 100.000 | 0.000 | 5.47 | 8.12 | 5.21 | 6.13 | 40.70 | 123.06 | 1.431 |
| qos | 2 | 5 | 7200 | 7200 | 100.000 | 0.000 | 6.46 | 6.35 | 5.54 | 8.76 | 10.99 | 126.73 | 0.819 |

## Latency without scan windows (ms; messages published within 1 s of an `iw event` scan removed)

| group | qos | scans | msgs_in_scan | noscan_lat_mean_ms | noscan_lat_jitter_ms | noscan_lat_p50_ms | noscan_lat_p95_ms | noscan_lat_p99_ms | noscan_lat_max_ms | noscan_lat_over20_pct |
|---|---|---|---|---|---|---|---|---|---|---|
| qos | 0 | 1 | 136 | 4.82 | 1.34 | 5.35 | 6.07 | 6.49 | 9.37 | 0.000 |
| qos | 1 | 2 | 275 | 4.60 | 1.39 | 5.19 | 6.05 | 6.46 | 9.35 | 0.000 |
| qos | 2 | 1 | 139 | 5.96 | 1.47 | 5.53 | 8.67 | 9.51 | 13.77 | 0.000 |

## Rates, payload, link

| group | qos | msgs_per_s | payload_kbps | agg_rate_nominal_kbps | agg_rate_measured_kbps | bmp280_rate_hz | bmp280_bytes | ina219_rate_hz | ina219_bytes | mpu6050_rate_hz | mpu6050_bytes | rssi_mean_dbm | rssi_min_dbm | scans | scan_time_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos | 0 | 24.02 | 52.78 | 52.73 | 52.78 | 2.00 | 195.87 | 2.00 | 200.65 | 20.02 | 289.94 | -42.5 | -48 | 1 | 1.24 |
| qos | 1 | 24.02 | 52.79 | 52.74 | 52.79 | 2.00 | 196.04 | 2.00 | 201.15 | 20.02 | 289.93 | -42.7 | -45 | 2 | 2.48 |
| qos | 2 | 24.02 | 52.78 | 52.74 | 52.78 | 2.00 | 195.54 | 2.00 | 200.79 | 20.02 | 289.99 | -42.6 | -45 | 1 | 1.24 |

## Age of Information (ms)

| group | qos | bmp280_aoi_avg_ms | bmp280_paoi_mean_ms | bmp280_paoi_max_ms | ina219_aoi_avg_ms | ina219_paoi_mean_ms | ina219_paoi_max_ms | mpu6050_aoi_avg_ms | mpu6050_paoi_mean_ms | mpu6050_paoi_max_ms |
|---|---|---|---|---|---|---|---|---|---|---|
| qos | 0 | 256.01 | 506.03 | 625.40 | 252.72 | 502.73 | 617.39 | 30.46 | 55.46 | 178.86 |
| qos | 1 | 256.31 | 506.32 | 619.62 | 253.08 | 503.08 | 612.59 | 30.64 | 55.64 | 173.20 |
| qos | 2 | 257.47 | 507.48 | 623.09 | 255.22 | 505.23 | 614.87 | 31.49 | 56.49 | 177.70 |

## Per run

| run | qos | duration_s | sent | received | pdr_pct | lat_mean_ms | lat_jitter_ms | lat_p50_ms | lat_p95_ms | lat_p99_ms | lat_max_ms | lat_over20_pct | agg_rate_measured_kbps | mpu6050_aoi_avg_ms | mpu6050_paoi_max_ms | rssi_mean_dbm | scans | scan_time_pct | clk_after_offset_ms | clk_log_max_lastrx_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos0_rep1 | 0 | 60 | 1440 | 1440 | 100.000 | 4.88 | 1.36 | 5.38 | 6.13 | 6.55 | 8.66 | 0.000 | 52.80 | 30.08 | 68.31 | -42.1 | 0 | 0.00 | -0.02 | 3.00 |
| qos0_rep2 | 0 | 60 | 1440 | 1440 | 100.000 | 4.87 | 1.32 | 5.38 | 6.13 | 6.49 | 8.92 | 0.000 | 52.80 | 30.08 | 62.15 | -42.4 | 0 | 0.00 | -0.00 | 17.00 |
| qos0_rep3 | 0 | 60 | 1440 | 1440 | 100.000 | 4.93 | 1.29 | 5.41 | 6.11 | 6.69 | 9.13 | 0.000 | 52.75 | 30.12 | 62.50 | -42.6 | 0 | 0.00 | -0.01 | 14.00 |
| qos0_rep4 | 0 | 60 | 1440 | 1440 | 100.000 | 6.98 | 13.18 | 5.31 | 6.32 | 85.43 | 128.86 | 3.750 | 52.76 | 32.17 | 178.86 | -42.1 | 1 | 6.21 | 0.01 | 8.00 |
| qos0_rep5 | 0 | 60 | 1440 | 1440 | 100.000 | 4.68 | 1.35 | 5.29 | 5.91 | 6.37 | 9.37 | 0.000 | 52.78 | 29.85 | 61.87 | -43.3 | 0 | 0.00 | -0.01 | 8.00 |
| qos1_rep1 | 1 | 60 | 1440 | 1440 | 100.000 | 6.89 | 12.24 | 5.45 | 6.46 | 77.32 | 123.06 | 3.472 | 52.80 | 32.12 | 173.20 | -42.4 | 1 | 6.19 | 0.01 | 4.00 |
| qos1_rep2 | 1 | 60 | 1440 | 1440 | 100.000 | 4.63 | 1.37 | 5.24 | 6.06 | 6.51 | 9.11 | 0.000 | 52.78 | 29.82 | 59.79 | -43.0 | 0 | 0.00 | 0.00 | 6.00 |
| qos1_rep3 | 1 | 60 | 1440 | 1440 | 100.000 | 4.71 | 1.37 | 5.22 | 6.13 | 6.49 | 9.35 | 0.000 | 52.79 | 29.90 | 61.33 | -42.6 | 0 | 0.00 | -0.00 | 7.00 |
| qos1_rep4 | 1 | 60 | 1440 | 1440 | 100.000 | 4.28 | 1.35 | 4.81 | 5.74 | 6.11 | 8.27 | 0.000 | 52.78 | 29.43 | 58.42 | -42.6 | 0 | 0.00 | 0.01 | 11.00 |
| qos1_rep5 | 1 | 60 | 1440 | 1440 | 100.000 | 6.84 | 12.94 | 5.23 | 6.71 | 86.28 | 121.59 | 3.681 | 52.78 | 31.93 | 171.61 | -42.7 | 1 | 6.19 | -0.00 | 13.00 |
| qos2_rep1 | 2 | 60 | 1440 | 1440 | 100.000 | 5.70 | 1.57 | 5.09 | 8.81 | 9.65 | 11.29 | 0.000 | 52.78 | 30.75 | 62.74 | -42.6 | 0 | 0.00 | 0.01 | 5.00 |
| qos2_rep2 | 2 | 60 | 1440 | 1440 | 100.000 | 8.73 | 13.65 | 5.74 | 9.74 | 92.97 | 126.73 | 4.097 | 52.74 | 33.64 | 177.70 | -42.9 | 1 | 6.20 | 0.01 | 13.00 |
| qos2_rep3 | 2 | 60 | 1440 | 1440 | 100.000 | 5.93 | 1.48 | 5.50 | 8.61 | 9.31 | 10.83 | 0.000 | 52.80 | 31.03 | 61.52 | -42.6 | 0 | 0.00 | -0.01 | 4.00 |
| qos2_rep4 | 2 | 60 | 1440 | 1440 | 100.000 | 5.89 | 1.37 | 5.39 | 8.32 | 9.14 | 13.77 | 0.000 | 52.81 | 30.91 | 66.02 | -42.7 | 0 | 0.00 | -0.00 | 7.00 |
| qos2_rep5 | 2 | 60 | 1440 | 1440 | 100.000 | 6.06 | 1.40 | 5.71 | 8.49 | 9.57 | 12.43 | 0.000 | 52.79 | 31.14 | 63.34 | -42.4 | 0 | 0.00 | -0.00 | 6.00 |
