import base64
import json
import logging
import os
from datetime import datetime, timezone

import boto3
from pydantic import ValidationError

from models import MomentumSignal, SectorSnapshot, VolumeSpike, VolatilitySpike

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ["S3_BUCKET_RAW"]
s3 = boto3.client("s3")

_MODELS = {
    "volume_spike": VolumeSpike,
    "momentum_signal": MomentumSignal,
    "volatility_spike": VolatilitySpike,
    "sector_snapshot": SectorSnapshot,
}
_PREFIXES = {
    "volume_spike": "silver/volume",
    "momentum_signal": "silver/momentum",
    "volatility_spike": "silver/volatility",
    "sector_snapshot": "silver/sector",
}


def lambda_handler(event, context):
    for record in event["Records"]:
        _process(record)  # S3 write failures propagate and trigger batch retry
    return {"statusCode": 200}


def _process(record: dict) -> None:
    raw = base64.b64decode(record["kinesis"]["data"])
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in Kinesis record — skipping")
        return

    signal_type = payload.get("signal_type")
    model_cls = _MODELS.get(signal_type)
    if model_cls is None:
        logger.error("Unknown signal_type: %s — skipping", signal_type)
        return

    try:
        model_cls.model_validate(payload)
    except ValidationError as exc:
        logger.error("Validation failed for %s: %s — skipping", signal_type, exc)
        return

    key = _s3_key(signal_type, payload)
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=raw)
    logger.info("Archived %s → s3://%s/%s", signal_type, S3_BUCKET, key)


def _s3_key(signal_type: str, payload: dict) -> str:
    prefix = _PREFIXES[signal_type]
    if signal_type == "sector_snapshot":
        dt = _parse_iso(payload["snapshot_ts"])
        date_path = dt.strftime("%Y/%m/%d")
        filename = payload["snapshot_ts"].replace(":", "-")
        return f"{prefix}/{date_path}/{filename}.json"
    else:
        dt = _parse_iso(payload["detected_at"])
        date_path = dt.strftime("%Y/%m/%d")
        filename = f"{payload['detected_at'].replace(':', '-')}_{payload['symbol']}"
        return f"{prefix}/{date_path}/{filename}.json"


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
