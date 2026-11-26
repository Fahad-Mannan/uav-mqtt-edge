# Metrics: `L1`

1 runs. Latency = laptop receive - Pi publish (first arrival). Jitter = std of latency. PDR from unique (topic, seq) in pi_log.csv vs rx.csv. Aggregate rate (Eq. 8) R = sum f_k S_k x 8, S_k = mean payload bytes (payload only): nominal = publisher rates (as in the abstract's Table 2), measured = received update rates. AoI from t_sample_ns at the laptop; pooled AoI = duration-weighted mean of run averages, peak = max over runs.

## Clock check

No run flagged (chrony LastRx <= 60 s and |offset| <= 1 ms after the run, and during it where side logging recorded chrony).

## Delivery and latency (pooled, ms)

| group | qos | runs | sent | received | pdr_pct | plr_pct | lat_mean_ms | lat_jitter_ms | lat_p50_ms | lat_p95_ms | lat_p99_ms | lat_max_ms | lat_over20_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos | 1 | 1 | 43200 | 43200 | 100.000 | 0.000 | 1.83 | 5.92 | 1.33 | 1.95 | 3.69 | 125.79 | 0.736 |

## Latency without scan windows (ms; messages published within 1 s of an `iw event` scan removed)

| group | qos | scans | msgs_in_scan | noscan_lat_mean_ms | noscan_lat_jitter_ms | noscan_lat_p50_ms | noscan_lat_p95_ms | noscan_lat_p99_ms | noscan_lat_max_ms | noscan_lat_over20_pct |
|---|---|---|---|---|---|---|---|---|---|---|
| qos | 1 | 6 | 824 | 1.35 | 0.36 | 1.33 | 1.91 | 2.32 | 7.49 | 0.000 |

## Rates, payload, link

| group | qos | msgs_per_s | payload_kbps | agg_rate_nominal_kbps | agg_rate_measured_kbps | bmp280_rate_hz | bmp280_bytes | ina219_rate_hz | ina219_bytes | mpu6050_rate_hz | mpu6050_bytes | rssi_mean_dbm | rssi_min_dbm | scans | scan_time_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos | 1 | 24.00 | 53.06 | 53.05 | 53.06 | 2.00 | 197.04 | 2.00 | 202.52 | 20.00 | 291.63 | -42.2 | -46 | 6 | 1.24 |

## Age of Information (ms)

| group | qos | bmp280_aoi_avg_ms | bmp280_paoi_mean_ms | bmp280_paoi_max_ms | ina219_aoi_avg_ms | ina219_paoi_mean_ms | ina219_paoi_max_ms | mpu6050_aoi_avg_ms | mpu6050_paoi_mean_ms | mpu6050_paoi_max_ms |
|---|---|---|---|---|---|---|---|---|---|---|
| qos | 1 | 251.99 | 501.99 | 620.83 | 251.75 | 501.75 | 624.76 | 26.84 | 51.82 | 176.69 |

## Per run

| run | qos | duration_s | sent | received | pdr_pct | lat_mean_ms | lat_jitter_ms | lat_p50_ms | lat_p95_ms | lat_p99_ms | lat_max_ms | lat_over20_pct | agg_rate_measured_kbps | mpu6050_aoi_avg_ms | mpu6050_paoi_max_ms | rssi_mean_dbm | scans | scan_time_pct | clk_after_offset_ms | clk_log_max_lastrx_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qos1_rep1 | 1 | 1800 | 43200 | 43200 | 100.000 | 1.83 | 5.92 | 1.33 | 1.95 | 3.69 | 125.79 | 0.736 | 53.06 | 26.84 | 176.69 | -42.2 | 6 | 1.24 | -0.01 |  |
