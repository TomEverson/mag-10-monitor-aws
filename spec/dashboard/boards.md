# Spec: Streamlit Dashboard

## Overview

The dashboard is a Streamlit application deployed on ECS Fargate. It queries
Redshift Serverless directly via `psycopg2` through `dashboard/queries.py`
and renders six tabs. All tabs share a sidebar date picker and a symbol
multi-select filter.

Entry point: `dashboard/streamlit_app.py`  
Query layer: `dashboard/queries.py`  
Auto-refresh: configurable sidebar selector (15 / 30 / 60 / 120 seconds)

Password authentication is enforced at startup via `DASHBOARD_PASSWORD`
(injected from AWS Secrets Manager by ECS task definition).

---

## Sidebar Controls

| Control              | Default     | Affects      |
|----------------------|-------------|--------------|
| Date picker          | Today       | All tabs     |
| Symbol multi-select  | All 10      | All tabs     |
| Auto-refresh interval| 30 seconds  | All tabs     |

---

## Tab 1: Live Signals

**Purpose:** Real-time view of recent signals and market state.

### Components

1. **Market Breadth Bar** — counts UP/DOWN/FLAT symbols from the latest
   `sector_snapshots` row per symbol. Displays a BULLISH / MIXED / BEARISH
   banner with trading advice.

2. **Signal Cluster Alert** — finds 2-minute buckets in the last 60 minutes
   where 3+ distinct symbols fired signals simultaneously. Shows a banner for
   clusters within the last 5 minutes and a collapsed history table.

3. **Session Leaderboard** — signal count per symbol today (volume + momentum +
   volatility), displayed as metric cards for the top 5.

4. **Opening Range Breakout** — identifies volume spikes that occurred after the
   first 30 minutes of the session and broke above/below the opening range
   high/low.

5. **Active Signals (last 10 min)** — unified feed of all three signal types.
   Each signal is scored 1–10 (`signal_score()`), displayed as cards (top 5)
   plus a bubble scatter chart (time vs price, bubble size = strength) and a
   signal-type pie chart.

### Backing queries

| Component            | Function                      |
|----------------------|-------------------------------|
| Market breadth       | `get_market_breadth()`        |
| Cluster alert        | `get_signal_clusters(minutes_back=60)` |
| Leaderboard          | `get_session_leaderboard()`   |
| ORB                  | `get_opening_range(date_str)` |
| Active signals       | `get_all_realtime_signals(minutes_back=10)` |

---

## Tab 2: Volume Analysis

### Components

1. **RVOL (Relative Volume)** — today's signal count vs 30-day historical
   average by trading hour. Bar chart coloured green (≥1.5x), amber (≥1.0x),
   red (<1.0x).

2. **Signal Activity by Hour** — dual subplot: signal count per hour (bar) +
   avg/max spike ratio trend (line). Today's date only.

3. **Signal Strength vs Price Move (30-day)** — avg absolute price move grouped
   by spike magnitude bucket (Mild / Moderate / Strong / Extreme). Uses
   sector_snapshots 15–30 min after each signal as exit price.

### Backing queries

| Component        | Function                                         |
|------------------|--------------------------------------------------|
| RVOL             | `get_rvol(date_str)`                             |
| Activity by hour | `get_best_hours(date_str)`                       |
| Strength vs move | `get_signal_strength(date_range_days=30)`        |

---

## Tab 3: Momentum & Correlation

### Components

1. **Multi-Signal Confirmation** — volume spikes that had a momentum signal
   within ±300 seconds. Scatter plot split by direction (UP/DOWN): x = seconds
   apart, y = spike ratio.

2. **Top Correlated Pairs (30-day)** — pairs of symbols that fired volume spikes
   within 600 seconds of each other, ranked by co-signal count.

### Backing queries

| Component              | Function                                      |
|------------------------|-----------------------------------------------|
| Multi-signal           | `get_multi_signal_confirmation(date_str)`     |
| Correlated pairs       | `get_stock_correlation(date_range_days=30)`   |

---

## Tab 4: Volatility & Sector

### Components

1. **Volatility Regime (7-day)** — daily volatility signal count (bar) + avg/max
   Z-score trend (line). Dual subplot.

2. **Sector Rotation by Hour** — grouped bar chart: volume / momentum / volatility
   signal counts per trading hour for the selected date.

### Backing queries

| Component         | Function                                       |
|-------------------|------------------------------------------------|
| Volatility regime | `get_volatility_regime(date_range_days=7)`     |
| Sector rotation   | `get_sector_rotation(date_str)`                |

---

## Tab 5: Analytics

### Components

1. **Signal Win Rate** — configurable lookback (7/14/30/60/90 days) and min
   spike ratio filter. Shows aggregate metric cards (total signals, win rate at
   1%+, avg return, 2%+ profitable) plus a win-rate bar chart and avg-return
   gauge.

2. **Win Rate by Symbol** — same lookback/filter, broken down per symbol.
   Horizontal bar chart + table. Excludes symbols with fewer than 3 signals.

3. **Per-Signal P&L (5/15/30 min)** — scatter plot of spike ratio vs price
   change at each exit window. Table of up to 200 rows.

### Backing queries

| Component       | Function                                            |
|-----------------|-----------------------------------------------------|
| Win rate        | `get_signal_accuracy(date_range_days, min_spike_ratio)` |
| By symbol       | `get_symbol_win_rates(date_range_days, min_spike_ratio)` |
| Per-signal P&L  | `get_per_signal_pnl(date_range_days)`               |

---

## Tab 6: ML Insights

**Purpose:** Visualise ML anomaly scores alongside algorithmic signals to
show how the model augments the detection layer.

### Components

1. **ML Score Distribution** — histogram of `ml_anomaly_score` for the
   selected date across all signal types. Annotated with p50/p90 lines.

2. **Score vs Signal Strength** — scatter plot: x = `spike_ratio` (volume
   signals) or `z_score` (volatility), y = `ml_anomaly_score`. Coloured by
   signal type.

3. **High-Confidence Signals** — table of signals where both the algorithmic
   threshold fired AND `ml_anomaly_score >= 0.75`. These are displayed as
   "ML-confirmed" signals in Tab 1's Active Signals feed.

4. **Model Version** — sidebar chip showing the currently deployed endpoint
   model package version and approval date (via `boto3` SageMaker describe).

### Backing queries

| Component            | Function                                           |
|----------------------|----------------------------------------------------|
| Score distribution   | `get_ml_score_distribution(date_str)`              |
| Score vs strength    | `get_ml_score_vs_strength(date_str)`               |
| High-confidence      | `get_ml_confirmed_signals(date_str, min_score=0.75)` |

---

## Deployment

The dashboard runs as an ECS Fargate service (`mag10-dashboard`). An ALB
(Application Load Balancer) fronts the Fargate service on port 8080.
Terraform provisions the ECS task execution role with permissions to read from
Secrets Manager and connect to the Redshift workgroup.

Environment variables injected by the ECS task definition:

| Variable             | Source             |
|----------------------|--------------------|
| `AWS_REGION`              | Task metadata    |
| `REDSHIFT_HOST`           | Terraform output |
| `REDSHIFT_DB`             | tfvar            |
| `REDSHIFT_USER`           | Secrets Manager  |
| `REDSHIFT_PASSWORD`       | Secrets Manager  |
| `DASHBOARD_PASSWORD`      | Secrets Manager  |
| `SAGEMAKER_ENDPOINT_NAME` | tfvar            |

### Database Connection

The dashboard connects via `psycopg2` using the Redshift Serverless endpoint:

```python
conn = psycopg2.connect(
    host=os.environ["REDSHIFT_HOST"],
    port=5439,
    dbname=os.environ["REDSHIFT_DB"],
    user=os.environ["REDSHIFT_USER"],
    password=os.environ["REDSHIFT_PASSWORD"],
    sslmode="require"
)
```

All queries use parameterised statements with `%s` placeholders (psycopg2
style) to prevent SQL injection.
