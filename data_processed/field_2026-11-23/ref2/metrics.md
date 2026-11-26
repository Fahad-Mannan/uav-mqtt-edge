# Metrics: `ref2`

3 runs. Latency = laptop receive - Pi publish (first arrival). Jitter = std of latency. PDR from unique (topic, seq) in pi_log.csv vs rx.csv. Aggregate rate (Eq. 8) R = sum f_k S_k x 8, S_k = mean payload bytes (payload only): nominal = publisher rates (as in the abstract's Table 2), measured = received update rates. AoI from t_sample_ns at the laptop; pooled AoI = duration-weighted mean of run averages, peak = max over runs.

## Clock check

No run flagged (chrony LastRx <= 60 s and |offset| <= 1 ms after the run, and during it where side logging recorded chrony).

## Delivery and latency (pooled, ms)

| group | distance_m | qos | runs | sent | received | pdr_pct | plr_pct | lat_mean_ms | lat_jitter_ms | lat_p50_ms | lat_p95_ms | lat_p99_ms | lat_max_ms | lat_over20_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos |  | 0 | 1 | 1440 | 1440 | 100.000 | 0.000 | 7.74 | 1.94 | 7.46 | 10.69 | 11.03 | 12.73 | 0.000 |
| qos |  | 1 | 1 | 1440 | 1440 | 100.000 | 0.000 | 9.33 | 1.36 | 10.00 | 10.50 | 10.76 | 13.07 | 0.000 |
| qos |  | 2 | 1 | 1440 | 1440 | 100.000 | 0.000 | 11.07 | 1.58 | 10.66 | 13.57 | 14.15 | 15.40 | 0.000 |
| distance_qos | 2 | 0 | 1 | 1440 | 1440 | 100.000 | 0.000 | 7.74 | 1.94 | 7.46 | 10.69 | 11.03 | 12.73 | 0.000 |
| distance_qos | 2 | 1 | 1 | 1440 | 1440 | 100.000 | 0.000 | 9.33 | 1.36 | 10.00 | 10.50 | 10.76 | 13.07 | 0.000 |
| distance_qos | 2 | 2 | 1 | 1440 | 1440 | 100.000 | 0.000 | 11.07 | 1.58 | 10.66 | 13.57 | 14.15 | 15.40 | 0.000 |

## Latency without scan windows (ms; messages published within 1 s of an `iw event` scan removed)

| group | distance_m | qos | scans | msgs_in_scan | noscan_lat_mean_ms | noscan_lat_jitter_ms | noscan_lat_p50_ms | noscan_lat_p95_ms | noscan_lat_p99_ms | noscan_lat_max_ms | noscan_lat_over20_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qos |  | 0 | 0 | 0 | 7.74 | 1.94 | 7.46 | 10.69 | 11.03 | 12.73 | 0.000 |
| qos |  | 1 | 0 | 0 | 9.33 | 1.36 | 10.00 | 10.50 | 10.76 | 13.07 | 0.000 |
| qos |  | 2 | 0 | 0 | 11.07 | 1.58 | 10.66 | 13.57 | 14.15 | 15.40 | 0.000 |
| distance_qos | 2 | 0 | 0 | 0 | 7.74 | 1.94 | 7.46 | 10.69 | 11.03 | 12.73 | 0.000 |
| distance_qos | 2 | 1 | 0 | 0 | 9.33 | 1.36 | 10.00 | 10.50 | 10.76 | 13.07 | 0.000 |
| distance_qos | 2 | 2 | 0 | 0 | 11.07 | 1.58 | 10.66 | 13.57 | 14.15 | 15.40 | 0.000 |

## Rates, payload, link

| group | distance_m | qos | msgs_per_s | payload_kbps | agg_rate_nominal_kbps | agg_rate_measured_kbps | bmp280_rate_hz | bmp280_bytes | ina219_rate_hz | ina219_bytes | mpu6050_rate_hz | mpu6050_bytes | rssi_mean_dbm | rssi_min_dbm | scans | scan_time_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos |  | 0 | 24.02 | 53.11 | 53.07 | 53.11 | 2.00 | 196.18 | 2.00 | 199.95 | 20.02 | 292.07 | -42.1 | -45 | 0 | 0.00 |
| qos |  | 1 | 24.02 | 53.12 | 53.08 | 53.12 | 2.00 | 195.76 | 2.00 | 200.42 | 20.02 | 292.10 | -41.5 | -43 | 0 | 0.00 |
| qos |  | 2 | 24.02 | 53.15 | 53.10 | 53.15 | 2.00 | 195.87 | 2.00 | 201.33 | 20.02 | 292.18 | -41.6 | -45 | 0 | 0.00 |
| distance_qos | 2 | 0 | 24.02 | 53.11 | 53.07 | 53.11 | 2.00 | 196.18 | 2.00 | 199.95 | 20.02 | 292.07 | -42.1 | -45 | 0 | 0.00 |
| distance_qos | 2 | 1 | 24.02 | 53.12 | 53.08 | 53.12 | 2.00 | 195.76 | 2.00 | 200.42 | 20.02 | 292.10 | -41.5 | -43 | 0 | 0.00 |
| distance_qos | 2 | 2 | 24.02 | 53.15 | 53.10 | 53.15 | 2.00 | 195.87 | 2.00 | 201.33 | 20.02 | 292.18 | -41.6 | -45 | 0 | 0.00 |

## Age of Information (ms)

| group | distance_m | qos | bmp280_aoi_avg_ms | bmp280_paoi_mean_ms | bmp280_paoi_max_ms | ina219_aoi_avg_ms | ina219_paoi_mean_ms | ina219_paoi_max_ms | mpu6050_aoi_avg_ms | mpu6050_paoi_mean_ms | mpu6050_paoi_max_ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qos |  | 0 | 258.41 | 508.44 | 511.71 | 255.10 | 505.12 | 510.73 | 32.95 | 57.95 | 69.37 |
| qos |  | 1 | 260.14 | 510.15 | 511.05 | 256.93 | 506.92 | 510.62 | 34.50 | 59.50 | 72.19 |
| qos |  | 2 | 262.92 | 512.94 | 514.87 | 259.63 | 509.65 | 514.89 | 36.05 | 61.04 | 70.85 |
| distance_qos | 2 | 0 | 258.41 | 508.44 | 511.71 | 255.10 | 505.12 | 510.73 | 32.95 | 57.95 | 69.37 |
| distance_qos | 2 | 1 | 260.14 | 510.15 | 511.05 | 256.93 | 506.92 | 510.62 | 34.50 | 59.50 | 72.19 |
| distance_qos | 2 | 2 | 262.92 | 512.94 | 514.87 | 259.63 | 509.65 | 514.89 | 36.05 | 61.04 | 70.85 |

## Per run

| run | point | qos | distance_m | duration_s | sent | received | pdr_pct | lat_mean_ms | lat_jitter_ms | lat_p50_ms | lat_p95_ms | lat_p99_ms | lat_max_ms | lat_over20_pct | agg_rate_measured_kbps | mpu6050_aoi_avg_ms | mpu6050_paoi_max_ms | rssi_mean_dbm | scans | scan_time_pct | clk_after_offset_ms | clk_log_max_lastrx_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| s01_ref_qos0 | ref | 0 | 2 | 60 | 1440 | 1440 | 100.000 | 7.74 | 1.94 | 7.46 | 10.69 | 11.03 | 12.73 | 0.000 | 53.11 | 32.95 | 69.37 | -42.1 | 0 | 0.00 | -0.17 | 24.00 |
| s02_ref_qos1 | ref | 1 | 2 | 60 | 1440 | 1440 | 100.000 | 9.33 | 1.36 | 10.00 | 10.50 | 10.76 | 13.07 | 0.000 | 53.12 | 34.50 | 72.19 | -41.5 | 0 | 0.00 | -0.17 | 11.00 |
| s03_ref_qos2 | ref | 2 | 2 | 60 | 1440 | 1440 | 100.000 | 11.07 | 1.58 | 10.66 | 13.57 | 14.15 | 15.40 | 0.000 | 53.15 | 36.05 | 70.85 | -41.6 | 0 | 0.00 | -0.17 | 11.00 |
