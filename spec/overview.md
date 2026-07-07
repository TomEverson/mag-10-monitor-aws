# Spec: Overview

## Purpose

mag10-monitor-aws is a real-time market intelligence pipeline running on AWS.
It ingests live trade data for 10 high-interest equities (MAG 7 + AMD, AVGO,
PLTR), runs four algorithmic signal detectors augmented by a SageMaker ML
anomaly scorer, and surfaces detected signals on a Streamlit dashboard backed
by Amazon Redshift.

The system extends the GCP-based mag10-monitor with a full ML pipeline:
on-demand model training, a SageMaker Model Registry, and real-time inference
integrated into the detection path.

It is intentionally minimal — two t3.micro EC2 instances, Lambda functions,
ECS Fargate for the dashboard, and SageMaker serverless/on-demand for ML.
It does not trade, place orders, or consume any paid market data feed beyond
the Finnhub free tier.

---

## Tracked Symbols

| Symbol | Name | Group |
|---|---|---|
| AAPL | Apple | MAG 7 |
| MSFT | Microsoft | MAG 7 |
| NVDA | NVIDIA | MAG 7 |
| GOOGL | Alphabet | MAG 7 |
| AMZN | Amazon | MAG 7 |
| META | Meta Platforms | MAG 7 |
| TSLA | Tesla | MAG 7 |
| AMD | Advanced Micro | Extended |
| AVGO | Broadcom | Extended |
| PLTR | Palantir | Extended |

All 10 symbols are subscribed in a single Finnhub WebSocket session.

---

## Signal Types

| Signal | What it detects | Cadence |
|---|---|---|
| `volume_spike` | Unusual trade volume burst for a symbol | On threshold breach |
| `momentum_signal` | Sustained directional price movement | On threshold breach |
| `volatility_spike` | Abnormal price variance within a window | On threshold breach |
| `sector_snapshot` | Periodic aggregate state across all symbols | Every 60 seconds |

Each signal also carries an `ml_anomaly_score` (0.0–1.0) from the SageMaker
IsolationForest endpoint, indicating how anomalous the current trade window is
for that symbol. Algorithmic detectors remain the primary signal gate; ML
scoring is additive.

---

## Data Layers

| Layer | Storage | Contents |
|---|---|---|
| **Bronze** | S3 (`bronze/`) | Raw validated trades — immutable, used for warm-start |
| **Silver** | S3 (`silver/`) | Detected signals — archived for audit and ML training |
| **Gold** | Redshift Serverless | Served directly to the Streamlit dashboard |

---

## Data Flow

```
Finnhub WebSocket
      │
      ▼
WebSocket EC2 (ingest only)
  validates raw trades
  publishes to Kinesis
      │
      ▼
Kinesis Data Stream: mag10-raw-trades
  ├──► Kinesis Data Firehose → S3 bronze/      (Bronze)
  ├──► Lambda (feature-eng) → SageMaker Feature Store
  └──► Detection EC2
         4 stateful detectors
         + SageMaker endpoint for ML anomaly score
         warm-starts from S3 bronze/ on restart
               │
               ▼
        Kinesis Data Stream: mag10-processed-signals
               │
               ▼
        Lambda (signal-archive)
        routes by signal_type
        ├──► silver/volume/
        ├──► silver/momentum/
        ├──► silver/volatility/
        └──► silver/sector/          (Silver S3)
               │
          S3 Event Notification
               │
               ▼
        Lambda (s3-to-redshift)
        routes by S3 path
        ├──► signals.volume_spikes
        ├──► signals.momentum_signals
        ├──► signals.volatility_spikes
        └──► signals.sector_snapshots  (Gold Redshift)
               │
               ▼
      Streamlit Dashboard (ECS Fargate)
```

---

## ML Pipeline Flow

```
On-Demand Trigger (API Gateway POST /retrain  or  scripts/trigger_training.sh)
      │
      ▼
SageMaker Pipeline: mag10-training-pipeline
  Step 1 — Processing Job (feature_engineering.py)
    Reads S3 bronze/, computes per-symbol features, writes to S3 features/
  Step 2 — Training Job (train.py)
    Trains IsolationForest on feature matrix, writes model artifacts to S3
  Step 3 — Processing Job (evaluate.py)
    Evaluates anomaly rate, writes metrics report to S3
  Step 4 — ConditionStep
    Passes if anomaly rate is within [0.03, 0.20]; otherwise halts
  Step 5 — RegisterModel
    Adds versioned model to SageMaker Model Registry with metrics
      │
      ▼
Manual approval in Model Registry → Update SageMaker Endpoint
      │
      ▼
Detection EC2 calls endpoint for every trade batch
```

---

## Spec Map

| File | What it covers |
|---|---|
| `spec/data-sources.md` | Finnhub WebSocket connection, message format, reconnection |
| `spec/detectors/volume.md` | Volume spike detector algorithm and thresholds |
| `spec/detectors/momentum.md` | Momentum signal detector algorithm and thresholds |
| `spec/detectors/volatility.md` | Volatility spike detector algorithm and thresholds |
| `spec/detectors/sector.md` | Sector snapshot aggregation and cadence |
| `spec/pipeline/listener.md` | WebSocket EC2 and Detection EC2 responsibilities |
| `spec/pipeline/bronze.md` | Bronze layer — S3 raw trade archive and warm-start |
| `spec/pipeline/kinesis.md` | Kinesis streams, consumers, and message schemas |
| `spec/pipeline/lambda.md` | Lambda function responsibilities (signal-archive, s3-to-redshift, feature-eng) |
| `spec/pipeline/redshift.md` | Redshift Serverless table schemas (full column definitions) |
| `spec/pipeline/ml.md` | ML pipeline — SageMaker training, registry, endpoint, inference integration |
| `spec/dashboard/boards.md` | Streamlit dashboard tab layout and backing queries |
| `spec/infra/resources.md` | AWS resource inventory and Terraform module map |

---

## Non-Goals

- No trading or order placement of any kind
- No options, futures, or non-equity instruments
- No pre-market or after-hours signal detection
- No alert routing (email, SMS, Slack) — dashboard is the only output surface
- No historical backfill — pipeline is live-forward only
- No automated model deployment — Model Registry approval and endpoint update are manual
