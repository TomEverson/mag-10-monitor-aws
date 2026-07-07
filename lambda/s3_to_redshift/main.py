import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3
from pydantic import ValidationError

from models import MomentumSignal, SectorSnapshot, VolumeSpike, VolatilitySpike

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ["S3_BUCKET_RAW"]
REDSHIFT_WORKGROUP = os.environ.get("REDSHIFT_WORKGROUP", "mag10-workgroup")
REDSHIFT_DB = os.environ["REDSHIFT_DB"]

s3 = boto3.client("s3")
redshift = boto3.client("redshift-data")

_ROUTING = {
    "volume":     ("volume_spike",    VolumeSpike),
    "momentum":   ("momentum_signal", MomentumSignal),
    "volatility": ("volatility_spike", VolatilitySpike),
    "sector":     ("sector_snapshot", SectorSnapshot),
}


def lambda_handler(event, context):
    for sqs_record in event["Records"]:
        body = json.loads(sqs_record["body"])
        for s3_record in body.get("Records", []):
            bucket = s3_record["s3"]["bucket"]["name"]
            key = s3_record["s3"]["object"]["key"]
            _process(bucket, key)
    return {"statusCode": 200}


def _process(bucket: str, key: str) -> None:
    parts = key.split("/")
    if len(parts) < 2 or parts[0] != "silver":
        logger.error("Unexpected S3 key: %s — skipping", key)
        return

    routing = _ROUTING.get(parts[1])
    if routing is None:
        logger.error("Unknown silver prefix '%s' in key %s — skipping", parts[1], key)
        return

    signal_type, model_cls = routing

    try:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception:
        logger.error("Failed to read s3://%s/%s — skipping", bucket, key, exc_info=True)
        return

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in s3://%s/%s — skipping", bucket, key)
        return

    try:
        signal = model_cls.model_validate(payload)
    except ValidationError as exc:
        logger.error("Validation failed for %s: %s — skipping", key, exc)
        return

    processed_at = _now()

    # S3 write failures raise and trigger SQS redelivery
    if signal_type == "volume_spike":
        _insert_volume(signal, processed_at)
    elif signal_type == "momentum_signal":
        _insert_momentum(signal, processed_at)
    elif signal_type == "volatility_spike":
        _insert_volatility(signal, processed_at)
    elif signal_type == "sector_snapshot":
        _insert_sector(signal, processed_at)


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

def _insert_volume(s: VolumeSpike, processed_at: str) -> None:
    sql = """
        INSERT INTO signals.volume_spikes (
            timestamp, detected_at, processed_at, symbol, price,
            trade_volume, avg_volume, spike_ratio, window_trade_count,
            window_span_secs, ml_anomaly_score
        ) VALUES (
            :timestamp, :detected_at, :processed_at, :symbol, :price,
            :trade_volume, :avg_volume, :spike_ratio, :window_trade_count,
            :window_span_secs, NULLIF(:ml_anomaly_score, 'NULL')::FLOAT8
        ) ON CONFLICT (detected_at, symbol) DO NOTHING
    """
    _exec(sql, [
        _p("timestamp",          _ts(s.trade_ts)),
        _p("detected_at",        _iso(s.detected_at)),
        _p("processed_at",       processed_at),
        _p("symbol",             s.symbol),
        _p("price",              s.price),
        _p("trade_volume",       s.trade_volume),
        _p("avg_volume",         s.avg_volume),
        _p("spike_ratio",        s.spike_ratio),
        _p("window_trade_count", s.window_trade_count),
        _p("window_span_secs",   s.window_span_secs),
        _p("ml_anomaly_score",   s.ml_anomaly_score),
    ])


def _insert_momentum(s: MomentumSignal, processed_at: str) -> None:
    sql = """
        INSERT INTO signals.momentum_signals (
            window_end_ts, window_start_ts, detected_at, processed_at, symbol,
            direction, candles_in_direction, total_candles, oldest_open,
            latest_close, pct_change, ml_anomaly_score
        ) VALUES (
            :window_end_ts, :window_start_ts, :detected_at, :processed_at, :symbol,
            :direction, :candles_in_direction, :total_candles, :oldest_open,
            :latest_close, :pct_change, NULLIF(:ml_anomaly_score, 'NULL')::FLOAT8
        ) ON CONFLICT (window_end_ts, symbol) DO NOTHING
    """
    _exec(sql, [
        _p("window_end_ts",        _ts(s.window_end_ts)),
        _p("window_start_ts",      _ts(s.window_start_ts)),
        _p("detected_at",          _iso(s.detected_at)),
        _p("processed_at",         processed_at),
        _p("symbol",               s.symbol),
        _p("direction",            s.direction),
        _p("candles_in_direction", s.candles_in_direction),
        _p("total_candles",        s.total_candles),
        _p("oldest_open",          s.oldest_open),
        _p("latest_close",         s.latest_close),
        _p("pct_change",           s.pct_change),
        _p("ml_anomaly_score",     s.ml_anomaly_score),
    ])


def _insert_volatility(s: VolatilitySpike, processed_at: str) -> None:
    sql = """
        INSERT INTO signals.volatility_spikes (
            timestamp, detected_at, processed_at, symbol, price,
            mean_price, std_dev, z_score, window_trade_count,
            window_span_secs, ml_anomaly_score
        ) VALUES (
            :timestamp, :detected_at, :processed_at, :symbol, :price,
            :mean_price, :std_dev, :z_score, :window_trade_count,
            :window_span_secs, NULLIF(:ml_anomaly_score, 'NULL')::FLOAT8
        ) ON CONFLICT (detected_at, symbol) DO NOTHING
    """
    _exec(sql, [
        _p("timestamp",          _ts(s.trade_ts)),
        _p("detected_at",        _iso(s.detected_at)),
        _p("processed_at",       processed_at),
        _p("symbol",             s.symbol),
        _p("price",              s.price),
        _p("mean_price",         s.mean_price),
        _p("std_dev",            s.std_dev),
        _p("z_score",            s.z_score),
        _p("window_trade_count", s.window_trade_count),
        _p("window_span_secs",   s.window_span_secs),
        _p("ml_anomaly_score",   s.ml_anomaly_score),
    ])


def _insert_sector(s: SectorSnapshot, processed_at: str) -> None:
    sql = """
        INSERT INTO signals.sector_snapshots (
            snapshot_ts, processed_at, symbol, last_price, open_price,
            pct_change, trade_count, total_volume, last_trade_ts, is_stale
        ) VALUES (
            :snapshot_ts, :processed_at, :symbol,
            NULLIF(:last_price, 'NULL')::FLOAT8, NULLIF(:open_price, 'NULL')::FLOAT8,
            NULLIF(:pct_change, 'NULL')::FLOAT8, :trade_count, :total_volume,
            NULLIF(:last_trade_ts, 'NULL')::TIMESTAMP, :is_stale::BOOLEAN
        ) ON CONFLICT (snapshot_ts, symbol) DO NOTHING
    """
    snapshot_ts = _iso(s.snapshot_ts)
    for entry in s.symbols:
        _exec(sql, [
            _p("snapshot_ts",   snapshot_ts),
            _p("processed_at",  processed_at),
            _p("symbol",        entry.symbol),
            _p("last_price",    entry.last_price),
            _p("open_price",    entry.open_price),
            _p("pct_change",    entry.pct_change),
            _p("trade_count",   entry.trade_count),
            _p("total_volume",  entry.total_volume),
            _p("last_trade_ts", _ts(entry.last_trade_ts) if entry.last_trade_ts is not None else None),
            _p("is_stale",      "true" if entry.is_stale else "false"),
        ])


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _p(name: str, value) -> dict:
    return {"name": name, "value": "NULL" if value is None else str(value)}


def _ts(unix_ms: int) -> str:
    return datetime.fromtimestamp(unix_ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )[:-3]


def _iso(s: str) -> str:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )[:-3]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _exec(sql: str, params: list[dict]) -> None:
    resp = redshift.execute_statement(
        WorkgroupName=REDSHIFT_WORKGROUP,
        Database=REDSHIFT_DB,
        Sql=sql,
        Parameters=params,
    )
    _poll(resp["Id"])


def _poll(stmt_id: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = redshift.describe_statement(Id=stmt_id)["Status"]
        if status == "FINISHED":
            return
        if status == "FAILED":
            raise RuntimeError(f"Redshift statement {stmt_id} failed")
        time.sleep(0.5)
    raise TimeoutError(f"Redshift statement {stmt_id} timed out after {timeout}s")
