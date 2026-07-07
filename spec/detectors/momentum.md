# Spec: Momentum Signal Detector

## Purpose

Detect when a symbol is exhibiting a sustained, consistent directional price
move across multiple 1-minute candles — distinguishing genuine momentum from
single-trade noise or transient spikes.

---

## Algorithm

The detector builds 1-minute candles from the raw trade stream and evaluates
directional consistency across a rolling window of completed candles.

### Candle Construction

Each symbol maintains an **in-progress candle** for the current minute and a
**deque of completed candles**.

A candle covers exactly one calendar minute (minute boundaries are UTC):
`[HH:MM:00.000, HH:MM:59.999]`.

On each incoming trade for a symbol:

1. Determine the trade's minute bucket: `minute = trade.t // 60_000` (Unix ms
   floored to the minute).
2. If `minute == current_candle[symbol].minute`: update the in-progress candle:
   - `high = max(high, trade.p)`
   - `low = min(low, trade.p)`
   - `close = trade.p`
   - `volume += trade.v`
3. If `minute > current_candle[symbol].minute`: the previous minute is
   complete. Finalise it and append to `completed_candles[symbol]`. Start a
   new in-progress candle with `open = close = trade.p`, `high = trade.p`,
   `low = trade.p`, `volume = trade.v`, `minute = minute`.
4. Trim `completed_candles[symbol]` to the last `MOMENTUM_CANDLE_WINDOW`
   entries.
5. If `len(completed_candles[symbol]) < MOMENTUM_CANDLE_WINDOW`, skip the
   signal check — insufficient history.
6. Evaluate directional consistency across `completed_candles[symbol]`
   (see below).

### Directional Consistency Check

For each completed candle, determine its direction:
- `UP` if `candle.close >= candle.open`
- `DOWN` if `candle.close < candle.open`

Count:
- `up_count = number of candles where direction == UP`
- `down_count = number of candles where direction == DOWN`

If `up_count >= MOMENTUM_MIN_AGREE`: emit a signal with `direction = "UP"`.  
If `down_count >= MOMENTUM_MIN_AGREE`: emit a signal with `direction = "DOWN"`.  
Otherwise: no signal.

The check runs once per **candle finalisation** (step 3), not on every trade.
Signals are not evaluated mid-candle.

---

## Configuration

All values live in `detection/config.py`.

| Constant                   | Default | Description |
|----------------------------|---------|-------------|
| `MOMENTUM_CANDLE_WINDOW`   | 5       | Number of completed 1-minute candles to evaluate |
| `MOMENTUM_MIN_AGREE`       | 3       | Minimum candles pointing the same direction to fire a signal |
| `MOMENTUM_COOLDOWN_SECS`   | 120     | Seconds before another momentum signal can fire for the same symbol |

With the defaults, a signal fires when 3 or more of the last 5 completed
1-minute candles agree on direction.

---

## Signal Payload

| Field               | Type    | Description |
|---------------------|---------|-------------|
| `signal_type`       | string  | Always `"momentum_signal"` |
| `symbol`            | string  | The equity symbol |
| `direction`         | string  | `"UP"` or `"DOWN"` |
| `candles_in_direction` | integer | Number of candles agreeing on direction |
| `total_candles`     | integer | Total candles evaluated (always equals `MOMENTUM_CANDLE_WINDOW` when a signal fires) |
| `oldest_open`       | float   | Open price of the oldest candle in the window |
| `latest_close`      | float   | Close price of the newest candle in the window |
| `pct_change`        | float   | `(latest_close - oldest_open) / oldest_open * 100`, rounded to 3 dp |
| `window_start_ts`   | integer | Unix ms of the start of the oldest candle's minute |
| `window_end_ts`     | integer | Unix ms of the end of the newest candle's minute |
| `detected_at`       | string  | ISO 8601 UTC timestamp when the signal was emitted |
| `ml_anomaly_score`  | float   | Anomaly score from SageMaker endpoint (0.0–1.0); `null` if unavailable |

### Example

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

---

## Cooldown

After a signal fires for a symbol, no further momentum signal fires for that
symbol for `MOMENTUM_COOLDOWN_SECS` seconds (wall-clock, `time.monotonic()`).
Candle construction and evaluation continue during the cooldown; the result
is simply suppressed.

---

## Edge Cases

- Candle evaluation only happens at minute boundaries (when a candle is
  finalised). If no new trade arrives to cross a minute boundary, no
  evaluation occurs — the candle remains in-progress indefinitely until the
  next trade.
- If a trade arrives with a timestamp earlier than the current minute (late
  trade — should be caught by data quality filtering in the listener), it is
  ignored for candle purposes; do not close the current candle early.
- On WebSocket reconnect, all candle state (in-progress and completed) is
  reset to empty. The cooldown timer is also reset.
- If both `up_count` and `down_count` meet the threshold simultaneously
  (only possible if `MOMENTUM_MIN_AGREE` is set ≤ `MOMENTUM_CANDLE_WINDOW / 2`,
  which the defaults prevent), the `UP` signal takes precedence.
