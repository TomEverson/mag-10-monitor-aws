# Spec: Redshift Serverless Tables

## Namespace & Workgroup

| Attribute | Value |
|---|---|
| Namespace | `mag10-namespace` |
| Workgroup | `mag10-workgroup` |
| Base capacity | 8 RPU (Redshift Processing Units) — scales automatically |
| Region | `us-east-1` |
| Database | `mag10` |
| Schema | `signals` |

All tables live in `mag10.signals.*`. The database and schema are created by
Terraform on first deploy.

---

## Partitioning & Sort Keys

All tables define a `DISTKEY` and `SORTKEY` to optimise dashboard queries.
Dashboard queries must include a `WHERE date_trunc('day', <timestamp_col>) = :date`
filter to take advantage of zone maps and minimise data scanned.

---

## Table: `signals.volume_spikes`

**Populated by:** Lambda `mag10-s3-to-redshift`  
**DISTKEY:** `symbol`  
**SORTKEY:** `timestamp`  
**Dedup constraint:** UNIQUE (`detected_at`, `symbol`)

| Column               | Type      | Nullable | Description |
|----------------------|-----------|----------|-------------|
| `timestamp`          | TIMESTAMP | NOT NULL | Trade timestamp (from `trade_ts` Unix ms → TIMESTAMP) |
| `detected_at`        | TIMESTAMP | NOT NULL | When the detector emitted the signal |
| `processed_at`       | TIMESTAMP | NOT NULL | When the Lambda processed the file |
| `symbol`             | VARCHAR(8)| NOT NULL | Equity symbol |
| `price`              | FLOAT8    | NOT NULL | Trade price at signal time (USD) |
| `trade_volume`       | FLOAT8    | NOT NULL | Volume of the triggering trade |
| `avg_volume`         | FLOAT8    | NOT NULL | Rolling window average volume |
| `spike_ratio`        | FLOAT8    | NOT NULL | `trade_volume / avg_volume` |
| `window_trade_count` | INT       | NOT NULL | Trades in the rolling window |
| `window_span_secs`   | FLOAT8    | NOT NULL | Actual window duration in seconds |
| `ml_anomaly_score`   | FLOAT8    | NULL     | IsolationForest anomaly score (0.0–1.0); NULL if endpoint unavailable |

---

## Table: `signals.momentum_signals`

**Populated by:** Lambda `mag10-s3-to-redshift`  
**DISTKEY:** `symbol`  
**SORTKEY:** `window_end_ts`  
**Dedup constraint:** UNIQUE (`window_end_ts`, `symbol`)

| Column                 | Type      | Nullable | Description |
|------------------------|-----------|----------|-------------|
| `window_end_ts`        | TIMESTAMP | NOT NULL | End of the newest candle's minute |
| `window_start_ts`      | TIMESTAMP | NOT NULL | Start of the oldest candle's minute |
| `detected_at`          | TIMESTAMP | NOT NULL | When the detector emitted the signal |
| `processed_at`         | TIMESTAMP | NOT NULL | When the Lambda processed the file |
| `symbol`               | VARCHAR(8)| NOT NULL | Equity symbol |
| `direction`            | VARCHAR(4)| NOT NULL | `'UP'` or `'DOWN'` |
| `candles_in_direction` | INT       | NOT NULL | Candles agreeing on direction |
| `total_candles`        | INT       | NOT NULL | Total candles evaluated |
| `oldest_open`          | FLOAT8    | NOT NULL | Open price of the oldest candle |
| `latest_close`         | FLOAT8    | NOT NULL | Close price of the newest candle |
| `pct_change`           | FLOAT8    | NOT NULL | `(latest_close - oldest_open) / oldest_open * 100` |
| `ml_anomaly_score`     | FLOAT8    | NULL     | Anomaly score; NULL if endpoint unavailable |

---

## Table: `signals.volatility_spikes`

**Populated by:** Lambda `mag10-s3-to-redshift`  
**DISTKEY:** `symbol`  
**SORTKEY:** `timestamp`  
**Dedup constraint:** UNIQUE (`detected_at`, `symbol`)

| Column               | Type      | Nullable | Description |
|----------------------|-----------|----------|-------------|
| `timestamp`          | TIMESTAMP | NOT NULL | Trade timestamp (from `trade_ts` Unix ms) |
| `detected_at`        | TIMESTAMP | NOT NULL | When the detector emitted the signal |
| `processed_at`       | TIMESTAMP | NOT NULL | When the Lambda processed the file |
| `symbol`             | VARCHAR(8)| NOT NULL | Equity symbol |
| `price`              | FLOAT8    | NOT NULL | Price of the triggering trade |
| `mean_price`         | FLOAT8    | NOT NULL | Window mean price |
| `std_dev`            | FLOAT8    | NOT NULL | Population std dev of window prices |
| `z_score`            | FLOAT8    | NOT NULL | `abs(price - mean_price) / std_dev` |
| `window_trade_count` | INT       | NOT NULL | Trades in the rolling window |
| `window_span_secs`   | FLOAT8    | NOT NULL | Actual window duration in seconds |
| `ml_anomaly_score`   | FLOAT8    | NULL     | Anomaly score; NULL if endpoint unavailable |

---

## Table: `signals.sector_snapshots`

**Populated by:** Lambda `mag10-s3-to-redshift`  
**DISTKEY:** `symbol`  
**SORTKEY:** `snapshot_ts`  
**Dedup constraint:** UNIQUE (`snapshot_ts`, `symbol`)

One row per symbol per snapshot. A single S3 file (10 symbols) produces 10 rows.

| Column          | Type       | Nullable | Description |
|-----------------|------------|----------|-------------|
| `snapshot_ts`   | TIMESTAMP  | NOT NULL | When the snapshot was taken |
| `processed_at`  | TIMESTAMP  | NOT NULL | When the Lambda processed the file |
| `symbol`        | VARCHAR(8) | NOT NULL | Equity symbol |
| `last_price`    | FLOAT8     | NULL     | Most recent trade price; NULL if no trades received |
| `open_price`    | FLOAT8     | NULL     | First trade price of the session; NULL if none |
| `pct_change`    | FLOAT8     | NULL     | Session price change %; NULL if price unavailable |
| `trade_count`   | INT        | NOT NULL | Trades received this session |
| `total_volume`  | FLOAT8     | NOT NULL | Cumulative session volume |
| `last_trade_ts` | TIMESTAMP  | NULL     | Timestamp of last trade; NULL if none |
| `is_stale`      | BOOLEAN    | NOT NULL | True if no trade in last `SECTOR_STALE_SECS` seconds |

---

## Timestamp Handling (all tables)

| Source field | Redshift column | Conversion |
|---|---|---|
| `trade_ts` (int, Unix ms) | `timestamp` | `TIMESTAMP 'epoch' + trade_ts/1000 * INTERVAL '1 second'` |
| `detected_at` (ISO 8601 string) | `detected_at` | Cast via Python `datetime.fromisoformat()` before insert |
| `snapshot_ts` (ISO 8601 string) | `snapshot_ts` | Same as above |
| `last_trade_ts` (int, Unix ms, or null) | `last_trade_ts` | Same conversion as `trade_ts`, or NULL |

All timestamps are stored in UTC.

---

## Insert Pattern

Lambda `mag10-s3-to-redshift` uses the Redshift Data API
(`redshift-data:ExecuteStatement`) with parameterised SQL:

```sql
INSERT INTO signals.volume_spikes (
    timestamp, detected_at, processed_at, symbol, price,
    trade_volume, avg_volume, spike_ratio, window_trade_count,
    window_span_secs, ml_anomaly_score
)
VALUES (:timestamp, :detected_at, :processed_at, :symbol, :price,
        :trade_volume, :avg_volume, :spike_ratio, :window_trade_count,
        :window_span_secs, :ml_anomaly_score)
ON CONFLICT (detected_at, symbol) DO NOTHING;
```

The function polls `DescribeStatement` until the query status is `FINISHED`
or `FAILED` (timeout: 30 seconds).

---

## Redshift Serverless IAM

The Lambda execution role must have:
- `redshift-serverless:GetCredentials`
- `redshift-data:ExecuteStatement`
- `redshift-data:DescribeStatement`
- `redshift-data:GetStatementResult`

The Redshift Serverless workgroup must grant `USAGE` and `INSERT` on
`signals.*` to the Lambda IAM role via resource policy or db-level GRANT.
