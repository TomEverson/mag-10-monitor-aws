import base64
import json
import logging
import math
import os
from collections import defaultdict
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

FEATURE_GROUP_NAME = os.environ.get("FEATURE_GROUP_NAME", "mag10-trade-features")
AWS_REGION = os.environ["AWS_REGION"]

feature_store = boto3.client("sagemaker-featurestore-runtime", region_name=AWS_REGION)


def lambda_handler(event, context):
    batches: dict[str, list[dict]] = defaultdict(list)

    for record in event["Records"]:
        try:
            raw = base64.b64decode(record["kinesis"]["data"])
            trade = json.loads(raw)
            batches[trade["s"]].append(trade)
        except Exception:
            logger.warning("Failed to decode Kinesis record", exc_info=True)

    for symbol, trades in batches.items():
        try:
            _put_features(symbol, trades)
        except Exception:
            # Must not raise — feature failures must not block the raw trade stream
            logger.error("Feature Store write failed for %s", symbol, exc_info=True)

    return {"statusCode": 200}


def _put_features(symbol: str, trades: list[dict]) -> None:
    prices = [t["p"] for t in trades]
    volumes = [t["v"] for t in trades]
    n = len(prices)
    mean_p = sum(prices) / n
    std_p = math.sqrt(sum((p - mean_p) ** 2 for p in prices) / n) if n > 1 else 0.0
    vol_sum = sum(volumes)
    pct_change = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] != 0 else 0.0
    event_time = datetime.fromtimestamp(
        max(t["t"] for t in trades) / 1000, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    feature_store.put_record(
        FeatureGroupName=FEATURE_GROUP_NAME,
        Record=[
            {"FeatureName": "symbol",            "ValueAsString": symbol},
            {"FeatureName": "event_time",        "ValueAsString": event_time},
            {"FeatureName": "batch_trade_count", "ValueAsString": str(n)},
            {"FeatureName": "price_mean",        "ValueAsString": str(mean_p)},
            {"FeatureName": "price_std",         "ValueAsString": str(std_p)},
            {"FeatureName": "price_min",         "ValueAsString": str(min(prices))},
            {"FeatureName": "price_max",         "ValueAsString": str(max(prices))},
            {"FeatureName": "volume_sum",        "ValueAsString": str(vol_sum)},
            {"FeatureName": "volume_mean",       "ValueAsString": str(vol_sum / n)},
            {"FeatureName": "volume_max",        "ValueAsString": str(max(volumes))},
            {"FeatureName": "price_change_pct",  "ValueAsString": str(pct_change)},
        ],
    )
    logger.info("Feature Store: %d trades → %s", n, symbol)
