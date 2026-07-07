# Spec: Sector Snapshot Detector

## Purpose

Publish a periodic snapshot of the current state of all 10 tracked symbols.
Unlike the other detectors, this is time-driven (every 60 seconds) rather than
threshold-driven. It provides the dashboard's sector heat map with a consistent
heartbeat of data.

---

## Cadence

The sector snapshot fires every `SECTOR_SNAPSHOT_INTERVAL_SECS` seconds
regardless of trade activity. If no trades have arrived for a symbol since the
last snapshot, that symbol's last-known state is used (see Stale Symbols below).

The snapshot timer runs independently of the trade stream. It is not triggered
by trades — it fires on a wall-clock interval.

---

## State Maintained Per Symbol

The sector detector tracks the following per-symbol state, updated on every
incoming trade:

| Field           | Description |
|-----------------|-------------|
| `last_price`    | Price of the most recently received trade |
| `open_price`    | Price of the first trade received after the detector started (or after the last reconnect) |
| `trade_count`   | Total number of trades received this session |
| `total_volume`  | Cumulative volume of all trades received this session |
| `last_trade_ts` | Timestamp of the most recently received trade (Unix milliseconds) |

`open_price` is set once per symbol on the first trade after startup or
reconnect, and is not updated thereafter until the next reconnect.

---

## Configuration

All values live in `detection/config.py`.

| Constant                          | Default | Description |
|-----------------------------------|---------|-------------|
| `SECTOR_SNAPSHOT_INTERVAL_SECS`   | 60      | Wall-clock interval between snapshots |
| `SECTOR_STALE_SECS`               | 120     | Seconds without a trade before a symbol is marked stale |

---

## Signal Payload

The snapshot publishes a single message containing all 10 symbols. Symbols
for which no trades have been received yet appear with `null` for price fields
and 0 for counts.

| Field       | Type    | Description |
|-------------|---------|-------------|
| `signal_type` | string | Always `"sector_snapshot"` |
| `snapshot_ts` | string | ISO 8601 UTC timestamp of when the snapshot was taken |
| `symbols`   | array   | One entry per tracked symbol (see Symbol Entry below) |

### Symbol Entry

| Field           | Type    | Description |
|-----------------|---------|-------------|
| `symbol`        | string  | Equity symbol |
| `last_price`    | float or null | Most recent trade price; null if no trades received |
| `open_price`    | float or null | First trade price of this session; null if no trades received |
| `pct_change`    | float or null | `(last_price - open_price) / open_price * 100`, rounded to 3 dp; null if either price is null |
| `trade_count`   | integer | Total trades received this session |
| `total_volume`  | float   | Cumulative volume this session |
| `last_trade_ts` | integer or null | Timestamp of last trade (Unix ms); null if no trades received |
| `is_stale`      | boolean | `true` if no trade received in the last `SECTOR_STALE_SECS` seconds |

### Example

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
    },
    {
      "symbol": "PLTR",
      "last_price": 22.08,
      "open_price": 21.90,
      "pct_change": 0.822,
      "trade_count": 304,
      "total_volume": 91200,
      "last_trade_ts": 1715172891000,
      "is_stale": false
    }
  ]
}
```

---

## Stale Symbols

A symbol is considered stale if no trade has arrived in the last
`SECTOR_STALE_SECS` seconds. Stale symbols still appear in the snapshot with
their last-known values; `is_stale` is set to `true`.

---

## Startup Behaviour

On startup, the sector detector emits no snapshot until the timer fires for the
first time (i.e. after the first `SECTOR_SNAPSHOT_INTERVAL_SECS` seconds). All
symbols with no trades yet will have null prices and `is_stale = false` (they
are not stale, just unseen).

---

## Reconnect Behaviour

On WebSocket reconnect, the per-symbol state is fully reset — `open_price`,
`trade_count`, `total_volume`, and `last_trade_ts` all revert to their initial
values. The snapshot timer is not reset; it continues on its wall-clock
interval.
