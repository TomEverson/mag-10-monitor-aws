import math
import time
from collections import deque
from datetime import datetime, timezone

from config import (
    SYMBOLS,
    VOLATILITY_COOLDOWN_SECS,
    VOLATILITY_MIN_WINDOW_SECS,
    VOLATILITY_WINDOW_SECS,
    VOLATILITY_Z_THRESHOLD,
)
from detectors.base import BaseDetector


class VolatilityDetector(BaseDetector):
    def __init__(self) -> None:
        self._windows: dict[str, deque] = {s: deque() for s in SYMBOLS}
        self._cooldowns: dict[str, float] = {}

    def process(self, trade: dict) -> dict | None:
        symbol = trade["s"]
        t = trade["t"]
        p = trade["p"]
        window = self._windows[symbol]

        window.append((t, p))
        cutoff = t - VOLATILITY_WINDOW_SECS * 1000
        while window and window[0][0] < cutoff:
            window.popleft()

        if len(window) < 2:
            return None
        span_ms = window[-1][0] - window[0][0]
        if span_ms < VOLATILITY_MIN_WINDOW_SECS * 1000:
            return None

        if time.monotonic() - self._cooldowns.get(symbol, 0.0) < VOLATILITY_COOLDOWN_SECS:
            return None

        prices = [price for _, price in window]
        mean_price = sum(prices) / len(prices)
        # Population std dev (divide by N, not N-1)
        std_dev = math.sqrt(sum((price - mean_price) ** 2 for price in prices) / len(prices))

        if std_dev == 0:
            return None

        z_score = abs(p - mean_price) / std_dev
        if z_score < VOLATILITY_Z_THRESHOLD:
            return None

        self._cooldowns[symbol] = time.monotonic()

        return {
            "signal_type": "volatility_spike",
            "symbol": symbol,
            "price": p,
            "mean_price": round(mean_price, 4),
            "std_dev": round(std_dev, 4),
            "z_score": round(z_score, 3),
            "window_trade_count": len(window),
            "window_span_secs": round(span_ms / 1000, 1),
            "trade_ts": t,
            "detected_at": _now_iso(),
            "ml_anomaly_score": None,
        }

    def reset(self) -> None:
        for s in SYMBOLS:
            self._windows[s].clear()
        self._cooldowns.clear()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
