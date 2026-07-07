from typing import Literal
from pydantic import BaseModel


class VolumeSpike(BaseModel):
    signal_type: Literal["volume_spike"]
    symbol: str
    price: float
    trade_volume: float
    avg_volume: float
    spike_ratio: float
    window_trade_count: int
    window_span_secs: float
    trade_ts: int
    detected_at: str
    ml_anomaly_score: float | None


class MomentumSignal(BaseModel):
    signal_type: Literal["momentum_signal"]
    symbol: str
    direction: Literal["UP", "DOWN"]
    candles_in_direction: int
    total_candles: int
    oldest_open: float
    latest_close: float
    pct_change: float
    window_start_ts: int
    window_end_ts: int
    detected_at: str
    ml_anomaly_score: float | None


class VolatilitySpike(BaseModel):
    signal_type: Literal["volatility_spike"]
    symbol: str
    price: float
    mean_price: float
    std_dev: float
    z_score: float
    window_trade_count: int
    window_span_secs: float
    trade_ts: int
    detected_at: str
    ml_anomaly_score: float | None


class SymbolEntry(BaseModel):
    symbol: str
    last_price: float | None
    open_price: float | None
    pct_change: float | None
    trade_count: int
    total_volume: float
    last_trade_ts: int | None
    is_stale: bool


class SectorSnapshot(BaseModel):
    signal_type: Literal["sector_snapshot"]
    snapshot_ts: str
    symbols: list[SymbolEntry]
