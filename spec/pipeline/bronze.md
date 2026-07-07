# Spec: Bronze Layer

## Overview

The Bronze layer is the immutable raw trade archive. Every validated trade
published by the WebSocket EC2 lands in S3 Bronze regardless of what the
Detection EC2 does. It serves two purposes:

1. **Durability** — raw trades are safe even if the Detection EC2 crashes.
2. **Warm-start** — the Detection EC2 reads Bronze on startup to rebuild
   rolling window state before connecting to Kinesis.
3. **ML Training data** — the SageMaker training pipeline reads Bronze S3 to
   build the feature matrix for IsolationForest training.

---

## S3 Path Structure

```
bronze/{YYYY}/{MM}/{DD}/{HH}/{symbol}/{trade_ts_ms}.json
```

Example:
```
bronze/2024/05/08/14/NVDA/1715172043000.json
```

All paths use lowercase prefixes. The file contains exactly one raw trade as JSON.

---

## Raw Trade Schema

The raw trade is the validated Finnhub trade object, written as-is with no
enrichment:

```json
{
  "s": "NVDA",
  "p": 875.30,
  "v": 48200,
  "t": 1715172043000
}
```

| Field | Type    | Description |
|-------|---------|-------------|
| `s`   | string  | Symbol |
| `p`   | float   | Trade price (USD) |
| `v`   | float   | Trade volume |
| `t`   | integer | Trade timestamp (Unix ms) |

This is the raw Finnhub format — no field renaming or enrichment.

---

## How Bronze is Written

The WebSocket EC2 publishes every validated raw trade to the `mag10-raw-trades`
Kinesis stream. A **Kinesis Data Firehose delivery stream** consumes from
`mag10-raw-trades` and writes batched records to the S3 Bronze prefix.

Firehose configuration:
- **Source:** Kinesis Data Stream `mag10-raw-trades`
- **Destination:** S3 bucket `mag10-data-prod`
- **S3 prefix:** `bronze/!{timestamp:yyyy}/!{timestamp:MM}/!{timestamp:dd}/!{timestamp:HH}/`
- **S3 error prefix:** `bronze-errors/`
- **Buffer size:** 5 MB
- **Buffer interval:** 60 seconds (flush at least every minute)
- **Compression:** GZIP

Firehose batches multiple trade records per S3 object (one object = up to 5 MB
or 60 seconds of trades). The warm-start procedure reads these batched files and
splits individual records by newline.

No Lambda code is required for Bronze writes — this is entirely infrastructure.

---

## Warm-Start Procedure

When the Detection EC2 starts (or restarts after a crash), it must rebuild
rolling window state before connecting to the Kinesis shard stream. The
warm-start procedure:

1. Determine the required lookback window:
   `max(VOLUME_WINDOW_SECS, VOLATILITY_WINDOW_SECS)` = 300 seconds.
2. List S3 objects under `bronze/{today}/{current_hour}/` and
   `bronze/{today}/{prev_hour}/` (to handle the hour boundary).
3. For each object, download and parse the GZIP-compressed NDJSON content.
   Each line is one raw trade JSON.
4. Filter trades where `trade_ts >= now_ms - 300_000`.
5. Feed each trade through all four detectors via `detector.process(trade)`
   in timestamp order. Discard any signals emitted during warm-start
   (do not publish to Kinesis — they are replays, not new signals).
6. Once warm-start is complete, begin consuming from Kinesis at `LATEST`.

Warm-start must complete before the Kinesis shard subscription is opened. If
warm-start fails (e.g. S3 is unavailable), the Detection EC2 logs a warning
and proceeds cold (detectors start with empty windows).

---

## Retention

Bronze objects are retained for **90 days** via an S3 lifecycle rule, then
deleted automatically. This matches the Silver retention policy.
