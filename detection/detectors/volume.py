import time
from collections import deque
from datetime import datetime, timezone

from config import (
    SYMBOLS,
    VOLUME_COOLDOWN_SECS,
    VOLUME_MIN_WINDOW_SECS,
    VOLUME_SPIKE_MULTIPLIER,
    VOLUME_WINDOW_SECS,
)
from detectors.base import BaseDetector


class VolumeDetector(BaseDetector):
    def __init__(self) -> None:
        self._windows: dict[str, deque] = {s: deque() for s in SYMBOLS}
        self._cooldowns: dict[str, float] = {}

    def process(self, trade: dict) -> dict | None:
        symbol = trade["s"]
        t = trade["t"]
        v = trade["v"]
        window = self._windows[symbol]

        window.append((t, v))
        cutoff = t - VOLUME_WINDOW_SECS * 1000
        while window and window[0][0] < cutoff:
            window.popleft()

        if len(window) < 2:
            return None
        span_ms = window[-1][0] - window[0][0]
        if span_ms < VOLUME_MIN_WINDOW_SECS * 1000:
            return None

        if time.monotonic() - self._cooldowns.get(symbol, 0.0) < VOLUME_COOLDOWN_SECS:
            return None

        # Average excludes the current trade (last entry)
        prior_volumes = [vol for _, vol in list(window)[:-1]]
        avg_volume = sum(prior_volumes) / len(prior_volumes)
        if avg_volume == 0:
            return None

        if v < avg_volume * VOLUME_SPIKE_MULTIPLIER:
            return None

        self._cooldowns[symbol] = time.monotonic()

        return {
            "signal_type": "volume_spike",
            "symbol": symbol,
            "price": trade["p"],
            "trade_volume": v,
            "avg_volume": round(avg_volume, 2),
            "spike_ratio": round(v / avg_volume, 2),
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
