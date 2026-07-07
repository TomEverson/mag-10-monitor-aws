import time
from collections import deque
from datetime import datetime, timezone
from typing import NamedTuple

from config import (
    MOMENTUM_CANDLE_WINDOW,
    MOMENTUM_COOLDOWN_SECS,
    MOMENTUM_MIN_AGREE,
    SYMBOLS,
)
from detectors.base import BaseDetector


class Candle(NamedTuple):
    minute: int   # trade.t // 60_000
    open: float
    high: float
    low: float
    close: float
    volume: float


class MomentumDetector(BaseDetector):
    def __init__(self) -> None:
        self._current: dict[str, Candle | None] = {s: None for s in SYMBOLS}
        self._completed: dict[str, deque] = {
            s: deque(maxlen=MOMENTUM_CANDLE_WINDOW) for s in SYMBOLS
        }
        self._cooldowns: dict[str, float] = {}

    def process(self, trade: dict) -> dict | None:
        symbol = trade["s"]
        t = trade["t"]
        p = trade["p"]
        v = trade["v"]
        minute = t // 60_000

        current = self._current[symbol]

        if current is None:
            self._current[symbol] = Candle(minute, p, p, p, p, v)
            return None

        if minute == current.minute:
            self._current[symbol] = Candle(
                current.minute,
                current.open,
                max(current.high, p),
                min(current.low, p),
                p,
                current.volume + v,
            )
            return None

        if minute < current.minute:
            # Late trade — ignore
            return None

        # New minute — finalise current candle and start a fresh one
        self._completed[symbol].append(current)
        self._current[symbol] = Candle(minute, p, p, p, p, v)

        completed = self._completed[symbol]
        if len(completed) < MOMENTUM_CANDLE_WINDOW:
            return None

        if time.monotonic() - self._cooldowns.get(symbol, 0.0) < MOMENTUM_COOLDOWN_SECS:
            return None

        candles = list(completed)
        up_count = sum(1 for c in candles if c.close >= c.open)
        down_count = sum(1 for c in candles if c.close < c.open)

        if up_count >= MOMENTUM_MIN_AGREE:
            direction, agree_count = "UP", up_count
        elif down_count >= MOMENTUM_MIN_AGREE:
            direction, agree_count = "DOWN", down_count
        else:
            return None

        self._cooldowns[symbol] = time.monotonic()

        oldest, newest = candles[0], candles[-1]
        pct_change = round((newest.close - oldest.open) / oldest.open * 100, 3)

        return {
            "signal_type": "momentum_signal",
            "symbol": symbol,
            "direction": direction,
            "candles_in_direction": agree_count,
            "total_candles": MOMENTUM_CANDLE_WINDOW,
            "oldest_open": oldest.open,
            "latest_close": newest.close,
            "pct_change": pct_change,
            "window_start_ts": oldest.minute * 60_000,
            "window_end_ts": (newest.minute + 1) * 60_000,
            "detected_at": _now_iso(),
            "ml_anomaly_score": None,
        }

    def reset(self) -> None:
        for s in SYMBOLS:
            self._current[s] = None
            self._completed[s].clear()
        self._cooldowns.clear()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
