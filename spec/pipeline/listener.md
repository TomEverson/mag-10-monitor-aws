# Spec: Listener Services

## Overview

The listener role is split across **two separate EC2 instances**:

| EC2 | Name | Responsibility |
|---|---|---|
| WebSocket EC2 | `mag10-websocket-ec2-prod` | Ingest raw trades from Finnhub, publish to Kinesis |
| Detection EC2 | `mag10-detection-ec2-prod` | Consume raw trades, run detectors + ML scorer, publish signals |

Both run on t3.micro instances. Neither writes to S3 or Redshift directly.

---

## WebSocket EC2

### Overview

The WebSocket EC2 is the only service with a Finnhub connection. Its sole
responsibility is to receive raw trades and publish them to the
`mag10-raw-trades` Kinesis stream. It performs no detection logic.

### Entry Point

`websocket/main.py`

1. Load configuration from environment variables via `config.py`.
2. Read `FINNHUB_API_KEY` from AWS Secrets Manager at startup.
3. Initialise the Kinesis publisher (`publisher.py`).
4. Open the WebSocket connection and enter the receive loop.
5. Handle SIGTERM and SIGINT gracefully — drain in-flight publishes, close
   WebSocket cleanly before exiting.

### Concurrency Model

asyncio throughout. All I/O (WebSocket receive, Kinesis publish) is async.

| Component | Async? | Notes |
|---|---|---|
| WebSocket receive loop | Yes | `async for message in ws` |
| Trade validation | No | Synchronous, sub-millisecond |
| Kinesis publish | Yes | Fire-and-forget with error callback |

### WebSocket Lifecycle

```
start
  │
  ▼
connect_with_backoff()
  │  opens wss://ws.finnhub.io?token=...
  │  subscribes all 10 symbols
  ▼
receive_loop()
  │  for each frame:
  │    if type == "trade": validate + put_record to mag10-raw-trades
  │    if type == "ping":  send pong
  │    else: log DEBUG, discard
  ▼
on_disconnect()
  │  log warning with close code and reason
  │  wait backoff delay
  └► connect_with_backoff()  (retry loop)
```

The WebSocket EC2 never exits the reconnect loop on its own — it retries
indefinitely until SIGTERM is received.

### Backoff Schedule

| Attempt | Delay |
|---|---|
| 1 | 5s |
| 2 | 10s |
| 3 | 20s |
| 4 | 40s |
| 5 | 80s |
| 6+ | 120s |

Delay resets to 5s after a connection open for at least 60 seconds.

### Trade Validation

Before publishing, each trade must pass validation:

1. `s` (symbol) must be in `SYMBOLS`.
2. `p` (price) must be present and > 0.
3. `v` (volume) must be present and ≥ 0.
4. `t` (timestamp ms) must be present.
5. Trade must not be stale: `now_ms - t <= 60_000` (60-second staleness cutoff).

Invalid trades are discarded silently (DEBUG log only).

### Publisher

`websocket/publisher.py` wraps `boto3.client("kinesis")`. It must:

- Serialise the raw trade dict to JSON (UTF-8 bytes).
- Call `kinesis.put_record(StreamName=..., Data=..., PartitionKey=symbol)`.
- Catch and log all exceptions at ERROR level — never raise to the caller.

### Configuration (`config.py`)

| Variable | Source | Description |
|---|---|---|
| `FINNHUB_API_KEY` | AWS Secrets Manager | Finnhub WebSocket auth |
| `AWS_REGION` | Env | AWS region |
| `KINESIS_STREAM_RAW_TRADES` | Env | Raw trades Kinesis stream name |
| `SYMBOLS` | `config.py` | Hardcoded set of 10 symbols |

### Logging

| Level | When |
|---|---|
| INFO | Startup, connected, reconnecting |
| WARNING | Disconnect, stale trade discarded |
| DEBUG | Every trade received, pings, discarded frames |
| ERROR | Publish failures, unhandled exceptions |

---

## Detection EC2

### Overview

The Detection EC2 consumes `mag10-raw-trades` via Kinesis Enhanced Fan-Out,
runs all four stateful detectors against each trade, optionally scores the
trade batch with the SageMaker ML endpoint, and publishes signals to
`mag10-processed-signals`. It has no Finnhub connection.

### Entry Point

`detection/main.py`

1. Load configuration from environment variables.
2. Read secrets from AWS Secrets Manager.
3. Run warm-start procedure (see `spec/pipeline/bronze.md`).
4. Register as an Enhanced Fan-Out consumer on `mag10-raw-trades`.
5. Enter the shard event stream receive loop.
6. Handle SIGTERM and SIGINT gracefully.

### Concurrency Model

asyncio throughout.

| Component | Async? | Notes |
|---|---|---|
| Kinesis Enhanced Fan-Out stream | Yes | `subscribe_to_shard` HTTP/2 streaming |
| Detector `.process(trade)` calls | No | Synchronous CPU work in event loop |
| Kinesis publish | Yes | Fire-and-forget with error callback |
| Sector snapshot timer | Yes | `asyncio.create_task` with `asyncio.sleep` loop |
| SageMaker endpoint call | Yes | `boto3` async wrapper or threadpool |

### Message Processing

For each raw trade record received from `mag10-raw-trades`:

1. Parse the JSON payload — fields `s`, `p`, `v`, `t`.
2. Call `detector.process(trade)` for each detector in order:
   volume → momentum → volatility → sector.
3. For each non-None result, call `ml_scorer.score(symbol, trade)` to
   attach `ml_anomaly_score` (see `spec/pipeline/ml.md`).
4. Publish the enriched signal to `mag10-processed-signals`.
5. Checkpoint the shard sequence number after each record batch.

### ML Scorer

`detection/ml_scorer.py` calls the SageMaker real-time endpoint:

```python
response = sagemaker_runtime.invoke_endpoint(
    EndpointName=SAGEMAKER_ENDPOINT_NAME,
    ContentType="application/json",
    Body=json.dumps(feature_vector)
)
anomaly_score = json.loads(response["Body"].read())["score"]
```

If the endpoint call fails (timeout, endpoint not found, any exception), the
scorer returns `None`. The signal is still published with `ml_anomaly_score: null`.
The ML scorer must never block signal emission.

### Detector Interface

Each detector in `detection/detectors/` implements `BaseDetector`:

```python
class BaseDetector(ABC):
    @abstractmethod
    def process(self, trade: dict) -> dict | None:
        """Return a signal dict if fired, None otherwise."""

    @abstractmethod
    def reset(self) -> None:
        """Reset all rolling windows (called on reconnect)."""
```

The sector detector's `process()` always returns `None` — it publishes
via a separate timer loop.

### Sector Snapshot Timer

```python
async def sector_snapshot_loop(sector_detector, publisher):
    while True:
        await asyncio.sleep(SECTOR_SNAPSHOT_INTERVAL_SECS)
        payload = sector_detector.get_snapshot()
        publisher.publish(stream_name, payload, partition_key="sector_snapshot")
```

### Configuration

| Variable | Source | Description |
|---|---|---|
| `AWS_REGION` | Env | AWS region |
| `KINESIS_STREAM_RAW_TRADES` | Env | Raw trades Kinesis stream name |
| `KINESIS_STREAM_PROCESSED` | Env | Processed signals stream name |
| `S3_BUCKET_RAW` | Env | Bronze/Silver S3 bucket name |
| `SAGEMAKER_ENDPOINT_NAME` | Env | SageMaker inference endpoint name |
| Detector constants | `config.py` | All thresholds and window sizes |
| `SYMBOLS` | `config.py` | Hardcoded set of 10 symbols |

### Logging

| Level | When |
|---|---|
| INFO | Startup, warm-start complete, signal detected |
| WARNING | Message parse error, publish failure, ML scorer timeout |
| DEBUG | Every trade processed |
| ERROR | Unhandled exception, repeated failures |

### Resource Constraints

Both EC2s run on t3.micro (2 vCPU, 1 GB RAM):

- Rolling windows use `collections.deque` — memory bounded.
- No disk writes from either EC2 process.
- Detection EC2: no outbound connection to Finnhub.
- WebSocket EC2: no detector state, minimal memory footprint.
