# Spec: ML Pipeline

## Overview

The ML pipeline adds anomaly scoring to the signal detection path. It trains
an IsolationForest model on historical trade feature data, registers it in the
SageMaker Model Registry, deploys it to a real-time endpoint, and integrates
it into the Detection EC2 via `detection/ml_scorer.py`.

The pipeline is triggered **on demand** — it does not run on a schedule.
Model updates require manual approval in the SageMaker Model Registry before
the endpoint is updated.

---

## Purpose

The algorithmic detectors use fixed thresholds (z-score ≥ 2.5, volume ×4.0,
etc.). The ML layer augments these with a learned anomaly score that adapts
to the feature distribution of recent trade activity.

The ML score does not gate signals — the algorithmic detectors fire regardless.
The score is an additive field (`ml_anomaly_score`) on every signal, surfaced
in the Redshift tables and the dashboard.

---

## Model

| Attribute | Value |
|---|---|
| Algorithm | `sklearn.ensemble.IsolationForest` |
| Task | Unsupervised anomaly detection (no labels required) |
| Training data | Historical Bronze S3 trade data — last N days |
| Features | Per-symbol trade window statistics (see Feature Schema below) |
| Output | Anomaly score normalised to [0.0, 1.0] (1.0 = most anomalous) |

### Feature Schema (model input)

Each record in the training matrix represents one Lambda batch window for one
symbol, as written to the SageMaker Feature Store by `mag10-feature-eng`.

| Feature | Description |
|---|---|
| `batch_trade_count` | Number of trades in the batch |
| `price_mean` | Mean trade price |
| `price_std` | Std dev of trade prices |
| `price_min` | Min trade price |
| `price_max` | Max trade price |
| `volume_sum` | Total trade volume |
| `volume_mean` | Mean trade volume |
| `volume_max` | Max single trade volume |
| `price_change_pct` | Price change % across the batch |

The `symbol` and `event_time` fields are used for grouping and joining only —
they are not model features.

---

## SageMaker Pipeline: mag10-training-pipeline

Defined in `ml/pipeline.py` using the SageMaker Pipelines SDK.

### Step 1 — Processing Job: feature_engineering

| Attribute | Value |
|---|---|
| Script | `ml/preprocessing/feature_engineering.py` |
| Instance | `ml.t3.medium` |
| Input | S3 Bronze (`s3://mag10-data-prod/bronze/`) — last 14 days |
| Output | S3 features (`s3://mag10-data-prod/features/`) — tabular feature matrix (CSV) |

Reads Firehose-batched NDJSON from Bronze, groups trades by symbol and 5-minute
window, computes the feature schema above per window, writes one CSV row per
(symbol, window). Includes train/validation split (80/20 by time — training on
earlier dates, validation on most recent 2 days).

### Step 2 — Training Job: train

| Attribute | Value |
|---|---|
| Script | `ml/training/train.py` |
| Instance | `ml.m5.large` |
| Framework | `sklearn` container (SageMaker built-in) |
| Input | S3 features train split |
| Output | S3 model artifacts (`s3://mag10-data-prod/models/`) |
| Hyperparameters | `n_estimators=200`, `contamination=0.1`, `random_state=42` |

Trains IsolationForest on the training split. Normalises anomaly scores to
[0.0, 1.0] using min-max scaling (fit on training set, applied to inference).
Saves both the IsolationForest model and the scaler as a single `joblib` pickle
to `model.tar.gz`.

### Step 3 — Processing Job: evaluate

| Attribute | Value |
|---|---|
| Script | `ml/evaluation/evaluate.py` |
| Instance | `ml.t3.medium` |
| Input | S3 model artifacts + S3 features validation split |
| Output | S3 evaluation report (`evaluation.json`) |

Loads the trained model, scores the validation set, and computes:
- `anomaly_rate` — fraction of validation records scored > 0.5
- `score_p50`, `score_p90`, `score_p99` — score percentiles
- `symbol_anomaly_rates` — per-symbol anomaly rate dict

Writes `evaluation.json` to the Processing Job output path.

### Step 4 — ConditionStep: check_anomaly_rate

Condition: `0.03 <= anomaly_rate <= 0.20`

- If **pass**: proceed to RegisterModel.
- If **fail**: halt pipeline; log the actual anomaly rate. No model is
  registered. The existing endpoint (if any) is unchanged.

### Step 5 — RegisterModel

Registers the model artifact in the SageMaker Model Registry under the
model package group `mag10-anomaly-detector`.

Model package metadata:
- `ModelApprovalStatus`: `PendingManualApproval`
- `ModelMetrics`: attaches the `evaluation.json` report
- `InferenceSpecification`: points to the sklearn inference container

---

## Model Registry

Model package group: `mag10-anomaly-detector`

Every successful pipeline run adds one version to this group. Versions are
automatically set to `PendingManualApproval`. An engineer must manually approve
a version in the AWS console (or via CLI) before it can be deployed.

```bash
aws sagemaker update-model-package \
    --model-package-arn <arn> \
    --model-approval-status Approved
```

---

## Endpoint Deployment

The endpoint is **not** updated automatically after registration. After manual
approval, update the endpoint using:

```bash
aws sagemaker update-endpoint \
    --endpoint-name mag10-anomaly-endpoint \
    --endpoint-config-name <new-config-name>
```

Or use `scripts/deploy_model.sh` which wraps the above.

### Endpoint Configuration

| Attribute | Value |
|---|---|
| Endpoint name | `mag10-anomaly-endpoint` |
| Instance type | `ml.t3.medium` (real-time inference) |
| Initial instance count | 1 |
| Container | SageMaker sklearn inference container |
| Inference script | `ml/inference/inference.py` |

---

## Inference Script: inference.py

`ml/inference/inference.py` is the SageMaker model server entry point.

```python
def model_fn(model_dir):
    return joblib.load(os.path.join(model_dir, "model.joblib"))

def input_fn(request_body, content_type):
    # expects JSON: {"features": [[f1, f2, ...], ...]}
    return np.array(json.loads(request_body)["features"])

def predict_fn(input_data, model):
    iso_forest, scaler = model
    raw_scores = iso_forest.decision_function(input_data)
    normalised = scaler.transform(raw_scores.reshape(-1, 1)).flatten()
    return normalised.clip(0.0, 1.0).tolist()

def output_fn(prediction, accept):
    # returns JSON: {"scores": [0.82, 0.71, ...]}
    return json.dumps({"scores": prediction}), "application/json"
```

### Request Format

```json
{
  "features": [
    [12, 183.12, 0.45, 182.80, 183.50, 24600, 2050, 8200, 0.177]
  ]
}
```

One row per symbol being scored. Fields must match the Feature Schema above
in the same order (9 floats).

### Response Format

```json
{
  "scores": [0.82]
}
```

One score per input row, in the same order.

---

## Integration with Detection EC2

`detection/ml_scorer.py` calls the endpoint once per detected signal:

```python
features = extract_features(symbol, recent_trades)
payload = {"features": [features]}
response = sagemaker_runtime.invoke_endpoint(
    EndpointName=SAGEMAKER_ENDPOINT_NAME,
    ContentType="application/json",
    Body=json.dumps(payload),
)
result = json.loads(response["Body"].read())
score = result["scores"][0]  # float 0.0–1.0
```

`extract_features(symbol, recent_trades)` computes the same feature vector as
the training pipeline (same 9 features, same order) over the last 100 trades
for that symbol held in a per-symbol deque.

If the call raises any exception (including `EndpointNotInService`), the scorer
returns `None` and logs at WARNING. The signal is published with
`ml_anomaly_score: null`.

---

## Automatic Trigger

Training runs automatically after every market close via **EventBridge Scheduler**.

| Attribute | Value |
|---|---|
| Schedule name | `mag10-retrain-schedule` |
| Cron expression | `cron(15 16 ? * MON-FRI *)` |
| Timezone | `America/New_York` |
| Target | `sagemaker:StartPipelineExecution` on `mag10-training-pipeline` |
| IAM role | `mag10-scheduler-role` |
| Flexible time window | Off |

The scheduler invokes `StartPipelineExecution` directly — no Lambda middleman. The execution display name is set to `scheduled-<date>` via the EventBridge input transformer.

There is no manual trigger. If a one-off retrain is needed, run:

```bash
aws sagemaker start-pipeline-execution \
    --pipeline-name mag10-training-pipeline \
    --pipeline-execution-display-name "manual-$(date +%Y%m%d-%H%M%S)"
```

---

## S3 Paths Summary

| Path | Contents |
|---|---|
| `s3://mag10-data-prod/bronze/` | Raw trade archives (Firehose output) |
| `s3://mag10-data-prod/features/` | Feature matrix output from Processing Job |
| `s3://mag10-data-prod/models/` | Training Job model artifacts |
| `s3://mag10-data-prod/evaluations/` | Evaluation report JSON files |
| `s3://mag10-data-prod/pipeline-logs/` | SageMaker Pipeline execution logs |
