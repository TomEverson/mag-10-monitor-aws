# Spec: Kinesis Data Streams & Message Schemas

## Streams

| Stream name | Published by | Consumed by | Trigger |
|---|---|---|---|
| `mag10-raw-trades` | WebSocket EC2 | Kinesis Firehose (Bronze) + Lambda (feature-eng) + Detection EC2 | Every validated trade |
| `mag10-processed-signals` | Detection EC2 | Lambda (signal-archive) | Every detected signal |

Stream names are stored in environment variables. Terraform creates the streams
with these exact names.

---

## mag10-raw-trades

### Producers

**WebSocket EC2** — publishes one record per validated trade using the `boto3`
Kinesis client `put_record` API.

```python
kinesis.put_record(
    StreamName="mag10-raw-trades",
    Data=json.dumps(trade).encode(),
    PartitionKey=trade["s"]   # symbol as partition key for per-symbol ordering
)
```

### Consumers

| Consumer | Type | Delivery |
|---|---|---|
| Kinesis Data Firehose | Enhanced fan-out or standard | Writes to S3 `bronze/` |
| Lambda `feature-eng` | Event source mapping (standard) | Feature engineering → SageMaker Feature Store |
| Detection EC2 | `GetRecords` polling (enhanced fan-out) | Stateful detection + ML scoring |

The Detection EC2 uses **Enhanced Fan-Out** (RegisterStreamConsumer) to receive
its own dedicated throughput (2 MB/s per shard) without competing with Lambda
consumers.

### Shard Count

1 shard (can handle up to 1,000 records/sec and 1 MB/sec write — more than
sufficient for 10 symbols on Finnhub free tier).

---

## mag10-processed-signals

### Producer

**Detection EC2** — publishes one record per detected signal.

```python
kinesis.put_record(
    StreamName="mag10-processed-signals",
    Data=json.dumps(signal).encode(),
    PartitionKey=signal["signal_type"]   # route by signal type
)
```

### Consumers

| Consumer | Type | Delivery |
|---|---|---|
| Lambda `signal-archive` | Event source mapping (standard) | Routes signals to S3 Silver |

### Shard Count

1 shard. Signal volume is far lower than raw trade volume.

---

## Data Retention

Both streams retain records for **7 days** (Kinesis default extended retention).
The Detection EC2 can reprocess records from the past 7 days if needed; in
practice, it always reads from `LATEST` after warm-start.

---

## Message Format

All records:
- Are JSON-encoded, UTF-8 bytes.
- Use the symbol (for `mag10-raw-trades`) or `signal_type` (for `mag10-processed-signals`)
  as the partition key.

---

## Raw Trade Schema (mag10-raw-trades)

```json
{
  "s": "NVDA",
  "p": 875.30,
  "v": 48200,
  "t": 1715172043000
}
```

| Field | Type | Description |
|---|---|---|
| `s` | string | Symbol |
| `p` | float | Trade price (USD) |
| `v` | float | Trade volume |
| `t` | integer | Trade timestamp (Unix ms) |

---

## Processed Signal Schemas (mag10-processed-signals)

All signal payloads include `ml_anomaly_score` (float 0.0–1.0, or `null`).
Full field definitions are in the detector specs under `spec/detectors/`.

### volume_spike

```json
{
  "signal_type": "volume_spike",
  "symbol": "NVDA",
  "price": 875.30,
  "trade_volume": 48200,
  "avg_volume": 11800.50,
  "spike_ratio": 4.08,
  "window_trade_count": 2341,
  "window_span_secs": 298.4,
  "trade_ts": 1715172043000,
  "detected_at": "2024-05-08T14:07:23.412Z",
  "ml_anomaly_score": 0.82
}
```

### momentum_signal

```json
{
  "signal_type": "momentum_signal",
  "symbol": "TSLA",
  "direction": "DOWN",
  "candles_in_direction": 4,
  "total_candles": 5,
  "oldest_open": 164.10,
  "latest_close": 162.80,
  "pct_change": -0.792,
  "window_start_ts": 1715171880000,
  "window_end_ts": 1715172180000,
  "detected_at": "2024-05-08T14:09:48.017Z",
  "ml_anomaly_score": 0.71
}
```

### volatility_spike

```json
{
  "signal_type": "volatility_spike",
  "symbol": "AMD",
  "price": 163.40,
  "mean_price": 158.4820,
  "std_dev": 1.9760,
  "z_score": 2.503,
  "window_trade_count": 1872,
  "window_span_secs": 299.6,
  "trade_ts": 1715172301000,
  "detected_at": "2024-05-08T14:11:41.889Z",
  "ml_anomaly_score": 0.91
}
```

### sector_snapshot

```json
{
  "signal_type": "sector_snapshot",
  "snapshot_ts": "2024-05-08T14:15:00.003Z",
  "symbols": [
    {
      "symbol": "AAPL",
      "last_price": 183.12,
      "open_price": 182.50,
      "pct_change": 0.340,
      "trade_count": 1842,
      "total_volume": 482300,
      "last_trade_ts": 1715172899000,
      "is_stale": false
    }
  ]
}
```

---

## Delivery Guarantees

Kinesis provides at-least-once delivery. Lambda `signal-archive` and Lambda
`s3-to-redshift` must both be idempotent — receiving the same record or S3
event twice must produce the same outcome.
