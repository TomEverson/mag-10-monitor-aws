# Spec: Lambda Functions

## Overview

There are three Lambda functions in this architecture:

| Function | Trigger | Responsibility |
|---|---|---|
| `mag10-signal-archive` | Kinesis `mag10-processed-signals` | Route by signal_type → write to S3 Silver |
| `mag10-s3-to-redshift` | S3 Event Notification (`silver/`) | Route by S3 path → COPY to correct Redshift table |
| `mag10-feature-eng` | Kinesis `mag10-raw-trades` | Compute features per symbol → ingest to SageMaker Feature Store |

All functions are deployed as container images from ECR (Python 3.12).

---

## Lambda: mag10-signal-archive

### Trigger

Kinesis event source mapping on `mag10-processed-signals`. Batch size: 10.
Starting position: `LATEST`.

### Responsibilities (in order)

1. **Iterate the Kinesis batch** — each event contains a list of records.
2. **Decode the record** — base64-decode `record["kinesis"]["data"]`, parse JSON.
3. **Read signal_type** — from the decoded payload `signal_type` field.
4. **Validate the payload** — use the matching Pydantic model from
   `shared/models.py`. If validation fails, log at ERROR and skip the record
   (do not raise — a bad record must not block the rest of the batch).
5. **Write to S3 Silver** — write the raw JSON bytes to the correct Silver
   path. If the S3 write fails, raise so Lambda retries the batch.
6. **Return success.**

### S3 Silver Path Structure

All paths use lowercase prefixes.

```
silver/volume/{YYYY}/{MM}/{DD}/{detected_at}_{symbol}.json
silver/momentum/{YYYY}/{MM}/{DD}/{detected_at}_{symbol}.json
silver/volatility/{YYYY}/{MM}/{DD}/{detected_at}_{symbol}.json
silver/sector/{YYYY}/{MM}/{DD}/{snapshot_ts}.json
```

The prefix is determined by `signal_type`. The raw JSON written is the
**original decoded payload** before any enrichment.

### Routing Table

| `signal_type` | S3 prefix | Pydantic model |
|---|---|---|
| `volume_spike` | `silver/volume/` | `VolumeSpike` |
| `momentum_signal` | `silver/momentum/` | `MomentumSignal` |
| `volatility_spike` | `silver/volatility/` | `VolatilitySpike` |
| `sector_snapshot` | `silver/sector/` | `SectorSnapshot` |

### Error Handling

| Scenario | Action |
|---|---|
| Unknown `signal_type` | Log ERROR; skip record (do not raise) |
| Pydantic validation fails | Log ERROR; skip record |
| S3 write fails | Raise exception; Lambda retries the batch |
| Unexpected exception | Raise exception; Lambda retries the batch |

---

## Lambda: mag10-s3-to-redshift

### Trigger

S3 Event Notification on bucket `mag10-data-prod`, prefix `silver/`, event
`s3:ObjectCreated:*`. Delivered via SQS queue to decouple and buffer events.

### Responsibilities (in order)

1. **Parse the S3 event** — extract bucket name and object key from the SQS
   message body (S3 → SQS → Lambda).
2. **Determine signal_type from path** — read the first path component after
   `silver/`:
   - `silver/volume/...` → `volume_spike`
   - `silver/momentum/...` → `momentum_signal`
   - `silver/volatility/...` → `volatility_spike`
   - `silver/sector/...` → `sector_snapshot`
3. **Download the file** — read the JSON bytes from S3.
4. **Validate the payload** — use the matching Pydantic model from
   `shared/models.py`. If validation fails, log ERROR and return without retry.
5. **Enrich the payload** — add `processed_at` (ISO 8601 UTC timestamp).
6. **Write to Redshift** — use `redshift-data` API (`execute_statement`) with
   a parameterised `INSERT INTO` statement. Use a deterministic deduplication
   key derived from signal fields (see Idempotency below).
7. **Return success.**

### Routing Table

| S3 prefix | Redshift table | Rows per file |
|---|---|---|
| `silver/volume/` | `signals.volume_spikes` | 1 |
| `silver/momentum/` | `signals.momentum_signals` | 1 |
| `silver/volatility/` | `signals.volatility_spikes` | 1 |
| `silver/sector/` | `signals.sector_snapshots` | 10 (one per symbol) |

### Idempotency

The Redshift table has a `UNIQUE` constraint on the deduplication key fields.
Inserts use `INSERT INTO ... ON CONFLICT DO NOTHING`.

| Signal type | Deduplication key fields |
|---|---|
| `volume_spike` | `detected_at` + `symbol` |
| `momentum_signal` | `window_end_ts` + `symbol` |
| `volatility_spike` | `detected_at` + `symbol` |
| `sector_snapshot` | `snapshot_ts` + `symbol` (per row) |

### Enrichment Fields

| Field | Type | Description |
|---|---|---|
| `processed_at` | string | ISO 8601 UTC when this Lambda processed the file |

### Error Handling

| Scenario | Action |
|---|---|
| Unknown S3 path prefix | Log ERROR; do not retry |
| S3 file not found | Log ERROR; do not retry |
| Pydantic validation fails | Log ERROR; do not retry |
| Redshift insert fails | Raise exception; SQS redelivers (up to 3 retries) |
| Unexpected exception | Raise exception; SQS redelivers |

---

## Lambda: mag10-feature-eng

### Trigger

Kinesis event source mapping on `mag10-raw-trades`. Batch size: 100.
Starting position: `LATEST`.

This Lambda runs **in addition to** the Detection EC2 — it processes the same
raw trades stream independently. It does not affect the detection path.

### Purpose

Compute a feature vector for each trade batch and ingest it into the
SageMaker Feature Store for offline use by the ML training pipeline.

### Responsibilities (in order)

1. **Decode the batch** — parse all Kinesis records in the event.
2. **Group by symbol** — aggregate the batch into per-symbol buckets.
3. **Compute features per symbol** (see Feature Schema below).
4. **Write to SageMaker Feature Store** — call `PutRecord` on the
   `mag10-trade-features` feature group for each symbol that has trades in
   the batch.
5. **Return success.**

If the Feature Store write fails, log at ERROR and continue — feature
engineering failures must not block raw data flow or trigger Kinesis retries.

### Feature Schema (mag10-trade-features feature group)

Computed over the trades in the current Lambda batch (approx. 100 trades).

| Feature | Type | Description |
|---|---|---|
| `symbol` | string | Equity symbol (record identifier) |
| `event_time` | string | ISO 8601 UTC timestamp of the latest trade in the batch |
| `batch_trade_count` | integer | Number of trades for this symbol in the batch |
| `price_mean` | float | Mean trade price in the batch |
| `price_std` | float | Std dev of trade prices in the batch (0 if single trade) |
| `price_min` | float | Min trade price in the batch |
| `price_max` | float | Max trade price in the batch |
| `volume_sum` | float | Total trade volume in the batch |
| `volume_mean` | float | Mean trade volume in the batch |
| `volume_max` | float | Max single trade volume in the batch |
| `price_change_pct` | float | `(last_price - first_price) / first_price * 100` across the batch |

These features are written to the **offline store** (S3 backing) for use by
the SageMaker training pipeline. The online store is not used.

---

## Shared Module

### shared/models.py

Pydantic v2 models for all four signal types. Both `mag10-signal-archive` and
`mag10-s3-to-redshift` import from this module. The module is copied into each
function directory at deploy time.

---

## Deployment Notes

- All functions are deployed as container images stored in ECR.
- Python 3.12 runtime.
- Memory: 256 MB for `signal-archive` and `feature-eng`; 512 MB for `s3-to-redshift`.
- Timeout: 60 seconds per invocation.
- `shared/` is copied into each function directory at build time.
- `requirements.txt` is generated with `uv pip compile` — never edited by hand.
