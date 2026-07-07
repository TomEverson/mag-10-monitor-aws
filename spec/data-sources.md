# Spec: Data Sources

## Finnhub WebSocket

**Endpoint:** `wss://ws.finnhub.io?token={FINNHUB_API_KEY}`

The listener connects to this endpoint on startup and subscribes to all 10
tracked symbols. This is the only external data source for the pipeline.

---

## Authentication

The API key is passed as a query parameter in the WebSocket URL. It is read
from the environment variable `FINNHUB_API_KEY`, which is populated at runtime
from AWS Secrets Manager. The key must never appear in source code, logs, or
committed files.

---

## Subscription

After the connection is established, the listener sends one subscription
message per symbol:

```json
{"type": "subscribe", "symbol": "AAPL"}
```

All 10 symbols are subscribed in sequence immediately after the connection
opens. The Finnhub free tier supports up to 50 simultaneous subscriptions;
10 is well within this limit.

---

## Incoming Message Format

Finnhub delivers trade data as JSON frames. Each frame may contain one or more
individual trades batched into the `data` array.

### Trade frame

```json
{
  "type": "trade",
  "data": [
    {
      "s": "AAPL",
      "p": 189.42,
      "v": 312,
      "t": 1715172000000,
      "c": ["1"]
    }
  ]
}
```

| Field | Type    | Description |
|-------|---------|-------------|
| `s`   | string  | Symbol (e.g. `"AAPL"`) |
| `p`   | float   | Trade price (USD) |
| `v`   | float   | Trade volume (number of shares) |
| `t`   | integer | Trade timestamp, Unix milliseconds UTC |
| `c`   | array   | Trade condition codes (may be null or empty — ignore for signal detection) |

The listener must iterate every object in `data` and dispatch each trade
individually to all detectors.

### Ping frame

```json
{"type": "ping"}
```

The listener must respond with a pong to keep the connection alive:

```json
{"type": "pong"}
```

### Other frames

Any frame with a `type` other than `"trade"` or `"ping"` must be logged at
DEBUG level and discarded.

---

## Market Hours

The Finnhub free-tier WebSocket delivers trades only during regular US equity
market hours:

- **Open:** 09:30 ET Monday–Friday
- **Close:** 16:00 ET Monday–Friday
- **Excluded:** weekends, US federal holidays

Outside market hours the WebSocket connection remains open but delivers no
trade frames. The listener must handle the no-trade window without crashing,
flooding reconnection attempts, or generating spurious signals.

---

## Reconnection Behaviour

| Event | Action |
|-------|--------|
| Clean close (code 1000/1001) | Reconnect after 5-second delay |
| Abnormal close / network error | Reconnect with exponential backoff: 5s, 10s, 20s, 40s … cap at 120s |
| Reconnect succeeds | Re-subscribe all 10 symbols; reset all detector rolling windows |
| Repeated failure (10+ attempts) | Log at ERROR level; continue retrying at 120s interval |

Detector rolling windows are reset on every reconnect because continuity of
the price/volume stream cannot be guaranteed after a gap.

---

## Data Quality

The listener must discard any trade where:

- `s` is not in the configured symbol list
- `p` is `null`, `0`, or negative
- `v` is `null` or negative
- `t` is more than 60 seconds in the past relative to system clock (stale trade)

Discarded trades must be counted per symbol and logged at DEBUG level. No
signal is generated from a discarded trade.
