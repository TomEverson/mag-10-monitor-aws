# AGENTS.md

## Project Overview

**mag10-monitor-aws** is a real-time market intelligence pipeline built on AWS.
It connects to the Finnhub WebSocket feed, detects market signals across MAG 10
stocks, augments them with a SageMaker ML anomaly scorer, and surfaces results
on a Streamlit dashboard backed by Redshift Serverless.

This project follows **spec-driven development**. Before writing any
implementation code, read the relevant spec file(s) in `/spec`. The spec
defines the contract — the code implements against it. If the spec and the
code disagree, the spec wins unless a spec change is explicitly approved.

This project is an AWS port of mag10-monitor (GCP). The detection algorithms
are identical. The infrastructure, SDK calls, and ML pipeline are new.

---

## Tracked Symbols

```
AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA  ← MAG 7
AMD, AVGO, PLTR                              ← Extended (MAG 10)
```

All 10 symbols are sourced via Finnhub WebSocket (`wss://ws.finnhub.io`).
Finnhub free tier supports up to 50 simultaneous symbol subscriptions.

---

## Architecture

```
Finnhub WebSocket
      │
      ▼
websocket/ (EC2 t3.micro)
  • maintains WebSocket connection
  • validates raw trades
  • publishes to Kinesis Data Stream: mag10-raw-trades
      │
      ├──► Kinesis Firehose → S3 bronze/         (Bronze layer)
      ├──► Lambda feature-eng → SageMaker Feature Store
      └──► detection/ (EC2 t3.micro)
             • pulls from mag10-raw-trades via Enhanced Fan-Out
             • runs 4 stateful detectors
             • calls SageMaker endpoint for ml_anomaly_score
             • publishes to Kinesis Data Stream: mag10-processed-signals
                    │
                    ▼
             Lambda signal-archive
               • routes by signal_type → S3 silver/
                    │
               S3 Event → SQS → Lambda s3-to-redshift
                    │
                    ▼
             Redshift Serverless (signals.*)
                    │
                    ▼
             Streamlit Dashboard (ECS Fargate)
               • Live Signals          (+ ML-confirmed signals)
               • Volume Analysis
               • Momentum & Correlation
               • Volatility & Sector
               • Analytics
               • ML Insights

Scheduled (weekdays 4:15pm ET):
  EventBridge Scheduler (mag10-retrain-schedule)
      │
      ▼
  SageMaker Pipeline: mag10-training-pipeline
    Processing → Training → Evaluation → ConditionStep → RegisterModel
      │
      ▼
  SageMaker Model Registry (manual approval)
      │
      ▼
  SageMaker Endpoint: mag10-anomaly-endpoint
```

---

## Repository Structure

```
mag10-monitor-aws/
├── spec/                          # Source of truth — read before coding
│   ├── overview.md
│   ├── data-sources.md
│   ├── detectors/
│   │   ├── volume.md
│   │   ├── momentum.md
│   │   ├── volatility.md
│   │   └── sector.md
│   ├── pipeline/
│   │   ├── listener.md
│   │   ├── kinesis.md
│   │   ├── bronze.md
│   │   ├── lambda.md
│   │   ├── redshift.md
│   │   └── ml.md
│   ├── dashboard/
│   │   └── boards.md
│   └── infra/
│       └── resources.md
│
├── websocket/                     # Runs on EC2 t3.micro
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── main.py                    # Entry point, WebSocket lifecycle
│   ├── config.py                  # Symbols, env vars
│   └── publisher.py               # boto3 Kinesis put_record wrapper
│
├── detection/                     # Runs on EC2 t3.micro
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── main.py                    # Entry point, Kinesis Enhanced Fan-Out consumer
│   ├── config.py                  # Detector thresholds, window sizes, symbols
│   ├── warm_start.py              # Reads S3 bronze/, replays trades through detectors
│   ├── publisher.py               # boto3 Kinesis put_record wrapper
│   ├── ml_scorer.py               # Calls SageMaker endpoint, returns anomaly score
│   └── detectors/
│       ├── base.py                # Abstract base detector
│       ├── volume.py
│       ├── momentum.py
│       ├── volatility.py
│       └── sector.py
│
├── lambda/                        # Lambda function packages
│   ├── shared/                    # Copied into each function at build time
│   │   └── models.py              # Pydantic signal models
│   ├── signal_archive/            # Kinesis mag10-processed-signals → S3 silver
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   ├── s3_to_redshift/            # S3 silver event → Redshift INSERT
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   ├── feature_eng/               # Kinesis mag10-raw-trades → SageMaker Feature Store
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   └── (no trigger_training Lambda — retraining is scheduled via EventBridge)
│
├── ml/                            # SageMaker ML pipeline scripts
│   ├── pipeline.py                # SageMaker Pipeline definition (boto3 Pipelines SDK)
│   ├── preprocessing/
│   │   └── feature_engineering.py # Processing Job: S3 bronze → feature matrix CSV
│   ├── training/
│   │   └── train.py               # Training Job: IsolationForest + scaler
│   ├── evaluation/
│   │   └── evaluate.py            # Processing Job: anomaly rate metrics → evaluation.json
│   └── inference/
│       └── inference.py           # SageMaker model server: model_fn, predict_fn, etc.
│
├── dashboard/                     # Runs on ECS Fargate
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── streamlit_app.py           # Streamlit UI (6 tabs)
│   └── queries.py                 # All Redshift query functions (psycopg2)
│
├── infra/                         # Terraform — all AWS resource definitions
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── modules/
│       ├── vpc/
│       ├── ec2/
│       ├── kinesis/
│       ├── s3/
│       ├── lambda/
│       ├── redshift/
│       ├── ecs/
│       ├── ecr/
│       ├── sagemaker/
│       ├── scheduler/     # EventBridge Scheduler for automatic retraining
│       └── iam/
│
├── scripts/
│   ├── deploy.sh                  # Full deploy: ECR push → terraform apply → Redshift schema
│   ├── deploy_lambdas.sh          # Lambda-only redeploy
│   ├── ec2-userdata-websocket.sh  # EC2 user-data: installs Docker + WebSocket systemd service
│   └── ec2-userdata-detection.sh  # EC2 user-data: installs Docker + Detection systemd service
│
├── AGENTS.md                      # This file
├── README.md
├── .env.example
└── .gitignore
```

---

## Spec-Driven Workflow

Every feature follows this order — do not skip steps:

1. **Read the spec** — find the relevant file under `/spec` before touching code
2. **Clarify before implementing** — if the spec is ambiguous or missing detail, ask before guessing
3. **Implement against the spec** — code should satisfy exactly what the spec defines, nothing more
4. **Update the spec if behaviour changes** — never silently diverge from the spec

If a spec file does not exist yet for the task at hand, create it first and
get confirmation before writing implementation code.

---

## Service Responsibilities

### websocket/
- Owns the Finnhub WebSocket connection
- Responsible for reconnection logic and graceful shutdown
- Publishes raw validated trades to `mag10-raw-trades` Kinesis stream
- Does not run detectors and does not write to S3 or Redshift
- Uses `boto3` `kinesis.put_record` — never the Pub/Sub SDK

### detection/
- Consumes `mag10-raw-trades` via Kinesis Enhanced Fan-Out (`subscribe_to_shard`)
- Runs all 4 detectors — each is stateful and holds its own rolling window
- Calls `ml_scorer.py` for every fired signal — the score is attached to the signal,
  never used to gate it
- Publishes enriched signals to `mag10-processed-signals` Kinesis stream
- Reads S3 Bronze on startup for warm-start (`warm_start.py`)
- Must not write to Redshift or S3 Silver directly — only publishes to Kinesis

### lambda/signal_archive/
- Triggered by `mag10-processed-signals` Kinesis stream (batch 10)
- Routes each signal to the correct S3 Silver prefix by `signal_type`
- Validates with Pydantic before writing — bad records are skipped, not retried
- S3 write failures raise an exception so Kinesis retries the batch

### lambda/s3_to_redshift/
- Triggered by SQS queue (backed by S3 event notifications on `silver/`)
- Reads the S3 object, validates with Pydantic, inserts to Redshift
- Uses `INSERT ... ON CONFLICT DO NOTHING` for idempotency
- Uses the Redshift Data API (`redshift-data:ExecuteStatement`) — not a persistent connection
- Redshift failures raise; SQS redelivers up to 3 times then dead-letters

### lambda/feature_eng/
- Triggered by `mag10-raw-trades` Kinesis stream (batch 100), independently of detection/
- Computes per-symbol feature vectors from the batch
- Writes to SageMaker Feature Store offline store only
- Must not raise on Feature Store failure — feature engineering errors must never
  block or retry the raw trade stream

### ml/
- `pipeline.py` defines the SageMaker Pipeline using the Pipelines SDK
- Each script (`feature_engineering.py`, `train.py`, `evaluate.py`, `inference.py`)
  runs in its own SageMaker managed container — no shared state with the live pipeline
- The model does not gate signals — it produces a score only
- Model updates require manual approval in the Model Registry before endpoint update

### infra/
- All AWS resources are defined here — never create resources manually in the console
- Each resource type has its own Terraform module
- Naming convention: `mag10-{resource-type}-{env}` (e.g. `mag10-kinesis-prod`)
- Secrets are managed via AWS Secrets Manager — never hardcoded or in `.env` files committed to git
- IAM follows least-privilege: each service has its own role with only the permissions it needs

### dashboard/queries.py
- Each function corresponds to exactly one dashboard component
- Queries use parameterised `psycopg2` statements (`%s` placeholders) — never f-strings with user input
- All queries against `volume_spikes`, `momentum_signals`, `volatility_spikes` must
  filter by `date_trunc('day', <sort_key_column>)` to exploit Redshift zone maps

---

## Kinesis Streams

| Stream | Published by | Consumed by |
|---|---|---|
| `mag10-raw-trades` | WebSocket EC2 | Firehose (Bronze) + Lambda feature-eng + Detection EC2 |
| `mag10-processed-signals` | Detection EC2 | Lambda signal-archive |

Partition key for `mag10-raw-trades`: symbol (`trade["s"]`)  
Partition key for `mag10-processed-signals`: signal_type (`signal["signal_type"]`)

Refer to `spec/pipeline/kinesis.md` for full message schemas.

---

## Redshift Tables

| Table | Populated by | SORTKEY |
|---|---|---|
| `signals.volume_spikes` | Lambda s3-to-redshift | `timestamp` |
| `signals.momentum_signals` | Lambda s3-to-redshift | `window_end_ts` |
| `signals.volatility_spikes` | Lambda s3-to-redshift | `timestamp` |
| `signals.sector_snapshots` | Lambda s3-to-redshift | `snapshot_ts` |

All tables have `ml_anomaly_score FLOAT8 NULL` — NULL when the SageMaker
endpoint was unavailable at signal time.

Refer to `spec/pipeline/redshift.md` for full column definitions.

---

## ML Pipeline

| Step | Script | Instance |
|---|---|---|
| Feature engineering | `ml/preprocessing/feature_engineering.py` | `ml.t3.medium` |
| Training | `ml/training/train.py` | `ml.m5.large` |
| Evaluation | `ml/evaluation/evaluate.py` | `ml.t3.medium` |
| Inference serving | `ml/inference/inference.py` | `ml.t3.medium` |

- Pipeline name: `mag10-training-pipeline`
- Model package group: `mag10-anomaly-detector`
- Endpoint name: `mag10-anomaly-endpoint`
- Trigger: EventBridge Scheduler `mag10-retrain-schedule` (weekdays 4:15pm ET)
- Model approval: **manual** in Model Registry before endpoint update

Refer to `spec/pipeline/ml.md` for algorithm details, feature schema,
condition thresholds, and inference request/response format.

---

## Environment Variables

Never hardcode credentials. All secrets live in AWS Secrets Manager.
Local development uses `.env` (never committed — see `.env.example`).

| Variable | Used by | Source | Description |
|---|---|---|---|
| `FINNHUB_API_KEY` | websocket | Secrets Manager | Finnhub WebSocket auth token |
| `AWS_REGION` | all services | EC2 instance metadata / env | AWS region |
| `KINESIS_STREAM_RAW_TRADES` | websocket, detection, feature-eng | env | Raw trades stream name |
| `KINESIS_STREAM_PROCESSED` | detection, signal-archive | env | Processed signals stream name |
| `S3_BUCKET_RAW` | detection (warm-start), signal-archive | env | S3 bucket for bronze + silver |
| `SAGEMAKER_ENDPOINT_NAME` | detection | env | SageMaker inference endpoint name |
| `REDSHIFT_HOST` | dashboard, s3-to-redshift | Terraform output | Redshift Serverless workgroup endpoint |
| `REDSHIFT_DB` | dashboard, s3-to-redshift | env | Redshift database name |
| `REDSHIFT_USER` | dashboard, s3-to-redshift | Secrets Manager | Redshift username |
| `REDSHIFT_PASSWORD` | dashboard, s3-to-redshift | Secrets Manager | Redshift password |
| `DASHBOARD_PASSWORD` | dashboard | Secrets Manager | Streamlit login password |

---

## Key Constraints

- **Finnhub WebSocket**: 50 symbol subscription limit on free tier — currently using 10
- **Market hours**: WebSocket delivers trades only during US market hours
  (9:30am–4:00pm ET, Mon–Fri). Both EC2s must handle the no-trade window
  without crashing or flooding reconnection attempts
- **Kinesis Enhanced Fan-Out**: Detection EC2 uses a registered shard consumer —
  do not poll with `GetRecords` on the same shard as Firehose or Lambda to avoid
  throughput contention
- **EC2 t3.micro**: 1 GB RAM — rolling windows are `collections.deque`, memory bounded.
  Never buffer unbounded trade history in memory
- **SageMaker endpoint**: `ml_scorer.py` must never block signal emission on timeout
  or endpoint unavailability. Catch all exceptions and return `None`
- **Redshift Data API**: `ExecuteStatement` is async — Lambda must poll
  `DescribeStatement` until `FINISHED` or `FAILED` (30-second timeout)
- **IsolationForest training**: contamination is set to 0.1 — do not tune this
  without updating `spec/pipeline/ml.md` and the ConditionStep thresholds
- **Lambda feature-eng**: must not raise on Feature Store failure (see Service Responsibilities)

---

## Package Management

This project uses **uv** exclusively. Do not use `pip` directly.

### Common commands

```bash
# Install dependencies from lockfile
uv sync

# Add a new dependency
uv add <package>

# Add a dev-only dependency
uv add --dev <package>

# Run a script inside the venv
uv run python main.py

# Generate requirements.txt (needed for Lambda zip deployment, if not using container images)
uv pip compile pyproject.toml -o requirements.txt
```

### Rules

- `uv.lock` is always committed — never gitignored
- `pyproject.toml` is the source of truth for dependencies — never edit `requirements.txt` by hand
- Each service (`websocket/`, `detection/`, `lambda/signal_archive/`, etc.) has its own
  isolated `pyproject.toml` and `uv.lock` — do not share a root-level lockfile
- `lambda/shared/` is copied into each Lambda function directory at Docker build time,
  not installed as a package

---

## AWS SDK Usage

All AWS interactions use **boto3**. Service client conventions:

| Service | Client | Used by |
|---|---|---|
| Kinesis | `boto3.client("kinesis")` | websocket, detection |
| S3 | `boto3.client("s3")` | detection (warm-start), signal-archive, s3-to-redshift |
| Secrets Manager | `boto3.client("secretsmanager")` | websocket, detection, dashboard |
| SageMaker Runtime | `boto3.client("sagemaker-runtime")` | detection (inference) |
| SageMaker | `boto3.client("sagemaker")` | ml/pipeline.py, dashboard (endpoint status) |
| SageMaker Feature Store | `boto3.client("sagemaker-featurestore-runtime")` | feature-eng |
| Redshift Data | `boto3.client("redshift-data")` | s3-to-redshift |

IAM credentials are provided by the EC2 instance profile or Lambda execution role —
never use access key IDs or secret access keys in code or environment variables.

---

## Deployment

```bash
# Full deploy (build images → ECR, terraform apply, wire Lambda triggers)
./scripts/deploy.sh

# Lambda-only redeploy (no infra changes)
./scripts/deploy_lambdas.sh

```

`deploy.sh` phases:
1. Build and push 6 Docker images to ECR (websocket, detection, dashboard, 3 Lambdas)
2. `terraform init && terraform apply` with image URI vars
3. Create Redshift schema (idempotent `IF NOT EXISTS`)
4. Print ALB DNS name (dashboard URL) and instructions for populating secrets

---

## What Not To Do

- Do not use `pip` directly — always use `uv`
- Do not write implementation code before reading the relevant spec
- Do not create AWS resources manually in the console — use Terraform in `infra/`
- Do not hardcode symbols, thresholds, stream names, or bucket names — all go in `config.py` or env vars
- Do not import across service boundaries (detection importing from lambda or vice versa)
- Do not write directly to Redshift from the Detection EC2 — only publish to Kinesis
- Do not gate signals on `ml_anomaly_score` — the score is additive, the algorithmic threshold is the gate
- Do not raise exceptions in `lambda/feature_eng/main.py` on Feature Store failures
- Do not use f-strings with user input in SQL queries — use `psycopg2` parameterised statements
- Do not use AWS access key IDs in code — rely on IAM roles attached to EC2/Lambda
- Do not commit `.env` files or any file containing credentials
- Do not manually edit `requirements.txt` — regenerate with `uv pip compile`
- Do not update the SageMaker endpoint without manual approval in the Model Registry first
