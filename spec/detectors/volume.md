# Spec: Volume Spike Detector

## Purpose

Detect when a single trade's volume is significantly larger than the recent
baseline for that symbol, indicating unusual buying or selling activity.

---

## Algorithm

Each symbol maintains an independent **time-based rolling window** of recent
trades. The window retains all trades whose timestamp falls within the last
`VOLUME_WINDOW_SECS` seconds, relative to the current trade's timestamp.

```
rolling_window[symbol] = list of (timestamp_ms, volume) tuples
```

On each incoming trade for a symbol:

1. Append `(trade.t, trade.v)` to `rolling_window[symbol]`.
2. Prune entries where `trade.t - entry.timestamp_ms > VOLUME_WINDOW_SECS * 1000`.
3. If the window does not span at least `VOLUME_MIN_WINDOW_SECS` seconds
   (i.e. `trade.t - rolling_window[symbol][0].timestamp_ms < VOLUME_MIN_WINDOW_SECS * 1000`),
   skip signal check — insufficient baseline.
4. Compute `avg_volume = mean(v for all entries except the current trade)`.
5. If `avg_volume == 0`, skip signal check.
6. If `trade.v >= avg_volume * VOLUME_SPIKE_MULTIPLIER`, emit a signal.

The current trade is excluded from the average to avoid self-reinforcement.
Pruning uses the **current trade's timestamp**, not wall-clock time, so the
window remains well-behaved during low-activity periods.

---

## Configuration

All values live in `detection/config.py`.

| Constant                   | Default | Description |
|----------------------------|---------|-------------|
| `VOLUME_WINDOW_SECS`       | 300     | Rolling window duration in seconds (5 minutes) |
| `VOLUME_MIN_WINDOW_SECS`   | 60      | Minimum window span before any signal can fire |
| `VOLUME_SPIKE_MULTIPLIER`  | 4.0     | Current trade volume must be ≥ this multiple of the window average |
| `VOLUME_COOLDOWN_SECS`     | 180     | Seconds before another volume spike signal can fire for the same symbol |

---

## Signal Payload

When a spike is detected, the detector emits a dict with the following fields.
This dict is serialised to JSON and published to the `mag10-processed-signals`
Kinesis stream with a `signal_type` partition key.

| Field             | Type    | Description |
|-------------------|---------|-------------|
| `signal_type`     | string  | Always `"volume_spike"` |
| `symbol`          | string  | The equity symbol (e.g. `"NVDA"`) |
| `price`           | float   | Trade price that triggered the signal |
| `trade_volume`    | float   | Volume of the triggering trade |
| `avg_volume`      | float   | Rolling window average volume (excl. current trade), rounded to 2 dp |
| `spike_ratio`     | float   | `trade_volume / avg_volume`, rounded to 2 dp |
| `window_trade_count` | integer | Number of trades in the window at signal time |
| `window_span_secs` | float  | Actual time span of the window in seconds, rounded to 1 dp |
| `trade_ts`        | integer | Trade timestamp from Finnhub (Unix milliseconds) |
| `detected_at`     | string  | ISO 8601 UTC timestamp when the signal was emitted by the detector |
| `ml_anomaly_score` | float  | Anomaly score from SageMaker endpoint (0.0–1.0); `null` if endpoint unavailable |

### Example

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

---

## Cooldown

After a signal fires for a symbol, no further volume spike signal fires for
that symbol for `VOLUME_COOLDOWN_SECS` seconds. Trades during the cooldown
period are still added to the rolling window and still prune stale entries.

The cooldown timer uses wall-clock time (`time.monotonic()`), not trade
timestamps, so it behaves correctly during low-activity gaps.

---

## Edge Cases

- If the window spans less than `VOLUME_MIN_WINDOW_SECS` seconds (e.g. early
  in the session or after a reconnect), no signal fires regardless of volume.
- If all previous trades in the window have volume 0, `avg_volume` is 0 and
  the check is skipped.
- The rolling window is reset to empty on WebSocket reconnect. The cooldown
  timer is also reset on reconnect.
