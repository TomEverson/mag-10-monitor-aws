import gzip
import json
import logging
import time
from datetime import datetime, timezone

import boto3

from config import AWS_REGION, S3_BUCKET_RAW, WARM_START_LOOKBACK_MS

logger = logging.getLogger(__name__)


def run(detectors: list) -> None:
    """Replay recent Bronze trades through detectors to rebuild rolling window state."""
    client = boto3.client("s3", region_name=AWS_REGION)
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - WARM_START_LOOKBACK_MS

    prefixes = _prefixes(datetime.now(timezone.utc))
    trades = []

    for prefix in prefixes:
        try:
            trades.extend(_load(client, prefix, cutoff_ms))
        except Exception:
            logger.warning("Warm-start: failed to load prefix %s — skipping", prefix, exc_info=True)

    if not trades:
        logger.warning("Warm-start: no trades found — starting cold.")
        return

    trades.sort(key=lambda t: t["t"])
    logger.info("Warm-start: replaying %d trades.", len(trades))

    for trade in trades:
        for detector in detectors:
            detector.process(trade)  # signals during warm-start are discarded

    logger.info("Warm-start complete.")


def _prefixes(now: datetime) -> list[str]:
    today = now.strftime("%Y/%m/%d")
    current_hour = f"{now.hour:02d}"
    prefixes = [f"bronze/{today}/{current_hour}/"]
    if now.hour > 0:
        prev_hour = f"{now.hour - 1:02d}"
        prefixes.append(f"bronze/{today}/{prev_hour}/")
    return prefixes


def _load(client, prefix: str, cutoff_ms: int) -> list[dict]:
    paginator = client.get_paginator("list_objects_v2")
    trades = []

    for page in paginator.paginate(Bucket=S3_BUCKET_RAW, Prefix=prefix):
        for obj in page.get("Contents", []):
            try:
                body = client.get_object(Bucket=S3_BUCKET_RAW, Key=obj["Key"])["Body"].read()
                data = gzip.decompress(body).decode("utf-8")
                for line in data.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    trade = json.loads(line)
                    if trade.get("t", 0) >= cutoff_ms:
                        trades.append(trade)
            except Exception:
                logger.warning("Warm-start: failed to parse %s — skipping", obj["Key"], exc_info=True)

    return trades
