# Spec: Volatility Spike Detector

## Purpose

Detect when a symbol's price is swinging abnormally within a recent time
window — i.e. high intra-window variance, not just a single large directional
move. This catches choppy, erratic behaviour that momentum alone would miss.

---

## Algorithm

Each symbol maintains an independent **time-based rolling window** of recent
trade prices. The window retains all trades whose timestamp falls within the
last `VOLATILITY_WINDOW_SECS` seconds, relative to the current trade's
timestamp.

```
rolling_window[symbol] = list of (timestamp_ms, price) tuples
```

On each incoming trade for a symbol:

1. Append `(trade.t, trade.p)` to `rolling_window[symbol]`.
2. Prune entries where `trade.t - entry.timestamp_ms > VOLATILITY_WINDOW_SECS * 1000`.
3. If the window does not span at least `VOLATILITY_MIN_WINDOW_SECS` seconds,
   skip signal check — insufficient baseline.
4. Extract prices: `prices = [p for (_, p) in rolling_window[symbol]]`.
5. Compute `mean_price = mean(prices)`.
6. Compute `std_dev = population standard deviation of prices`.
7. If `std_dev == 0`, skip (all prices identical — no volatility).
8. Compute `z_score = abs(trade.p - mean_price) / std_dev`.
9. If `z_score >= VOLATILITY_Z_THRESHOLD`, emit a signal.

The current trade **is included** in the window before computing the z-score.
The z-score measures how far the current price deviates from the full window
distribution (including itself).

Pruning uses the **current trade's timestamp**, so the window remains
well-behaved during low-activity periods.

---

## Configuration

All values live in `detection/config.py`.

| Constant                      | Default | Description |
|-------------------------------|---------|-------------|
| `VOLATILITY_WINDOW_SECS`      | 300     | Rolling window duration in seconds (5 minutes) |
| `VOLATILITY_MIN_WINDOW_SECS`  | 60      | Minimum window span before any signal can fire |
| `VOLATILITY_Z_THRESHOLD`      | 2.5     | Z-score threshold for a spike |
| `VOLATILITY_COOLDOWN_SECS`    | 120     | Seconds before another volatility spike can fire for the same symbol |

---

## Signal Payload

| Field              | Type    | Description |
|--------------------|---------|-------------|
| `signal_type`      | string  | Always `"volatility_spike"` |
| `symbol`           | string  | The equity symbol |
| `price`            | float   | Price of the triggering trade |
| `mean_price`       | float   | Mean price across the window (rounded to 4 dp) |
| `std_dev`          | float   | Population standard deviation of window prices (rounded to 4 dp) |
| `z_score`          | float   | `abs(price - mean_price) / std_dev` (rounded to 3 dp) |
| `window_trade_count` | integer | Number of trades in the window at signal time |
| `window_span_secs` | float   | Actual time span of the window in seconds, rounded to 1 dp |
| `trade_ts`         | integer | Trade timestamp from Finnhub (Unix milliseconds) |
| `detected_at`      | string  | ISO 8601 UTC timestamp when the signal was emitted |
| `ml_anomaly_score` | float   | Anomaly score from SageMaker endpoint (0.0–1.0); `null` if unavailable |

### Example

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

---

## Cooldown

After a signal fires for a symbol, no further volatility spike fires for that
symbol for `VOLATILITY_COOLDOWN_SECS` seconds (wall-clock, `time.monotonic()`).
The rolling window continues accumulating and pruning trades during the cooldown.

---

## Edge Cases

- If the window spans less than `VOLATILITY_MIN_WINDOW_SECS` seconds (e.g.
  early in the session or after a reconnect), no signal fires regardless of
  z-score.
- If `std_dev == 0` (all prices in the window are identical), the z-score is
  undefined — skip the check.
- Population standard deviation is used (divides by N, not N-1) because the
  window represents the full recent population of interest, not a sample.
- The rolling window and cooldown timer are both reset on WebSocket reconnect.
