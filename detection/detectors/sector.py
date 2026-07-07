import time
from datetime import datetime, timezone

from config import SECTOR_STALE_SECS, SYMBOLS
from detectors.base import BaseDetector


class SectorDetector(BaseDetector):
    def __init__(self) -> None:
        self._state: dict[str, dict] = {s: _empty() for s in SYMBOLS}

    def process(self, trade: dict) -> None:
        state = self._state[trade["s"]]
        if state["open_price"] is None:
            state["open_price"] = trade["p"]
        state["last_price"] = trade["p"]
        state["trade_count"] += 1
        state["total_volume"] += trade["v"]
        state["last_trade_ts"] = trade["t"]
        return None

    def get_snapshot(self) -> dict:
        now_ms = int(time.time() * 1000)
        entries = []

        for symbol in sorted(SYMBOLS):
            state = self._state[symbol]
            last_price = state["last_price"]
            open_price = state["open_price"]
            last_ts = state["last_trade_ts"]

            pct_change = (
                round((last_price - open_price) / open_price * 100, 3)
                if last_price is not None and open_price is not None
                else None
            )
            # Unseen symbols (last_ts is None) are not stale — just unobserved
            is_stale = (now_ms - last_ts) > SECTOR_STALE_SECS * 1000 if last_ts is not None else False

            entries.append({
                "symbol": symbol,
                "last_price": last_price,
                "open_price": open_price,
                "pct_change": pct_change,
                "trade_count": state["trade_count"],
                "total_volume": state["total_volume"],
                "last_trade_ts": last_ts,
                "is_stale": is_stale,
            })

        return {
            "signal_type": "sector_snapshot",
            "snapshot_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "symbols": entries,
        }

    def reset(self) -> None:
        for s in SYMBOLS:
            self._state[s] = _empty()


def _empty() -> dict:
    return {
        "last_price": None,
        "open_price": None,
        "trade_count": 0,
        "total_volume": 0.0,
        "last_trade_ts": None,
    }
