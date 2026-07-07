import asyncio
import json
import logging
from collections import deque

import boto3

from config import AWS_REGION, SAGEMAKER_ENDPOINT_NAME, SYMBOLS

logger = logging.getLogger(__name__)

_BUFFER_SIZE = 100
_buffers: dict[str, deque] = {s: deque(maxlen=_BUFFER_SIZE) for s in SYMBOLS}
_client = boto3.client("sagemaker-runtime", region_name=AWS_REGION)


def update(trade: dict) -> None:
    _buffers[trade["s"]].append(trade)


async def score(symbol: str) -> float | None:
    trades = list(_buffers[symbol])
    if not trades:
        return None
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _invoke, trades),
            timeout=2.0,
        )
    except Exception:
        logger.warning("ML scorer failed for %s — using null score", symbol, exc_info=True)
        return None


def _invoke(trades: list[dict]) -> float:
    features = _extract(trades)
    body = json.dumps({"features": [features]})
    response = _client.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT_NAME,
        ContentType="application/json",
        Body=body,
    )
    return json.loads(response["Body"].read())["scores"][0]


def _extract(trades: list[dict]) -> list[float]:
    prices = [t["p"] for t in trades]
    volumes = [t["v"] for t in trades]
    n = len(prices)
    mean_p = sum(prices) / n
    std_p = (sum((p - mean_p) ** 2 for p in prices) / n) ** 0.5
    vol_sum = sum(volumes)
    pct_change = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] != 0 else 0.0
    return [
        float(n),
        mean_p,
        std_p,
        min(prices),
        max(prices),
        vol_sum,
        vol_sum / n,
        max(volumes),
        pct_change,
    ]


def reset() -> None:
    for s in SYMBOLS:
        _buffers[s].clear()
