import asyncio
import json
import logging

import boto3

from config import AWS_REGION, KINESIS_STREAM_RAW_TRADES

logger = logging.getLogger(__name__)


class KinesisPublisher:
    def __init__(self) -> None:
        self._client = boto3.client("kinesis", region_name=AWS_REGION)

    def _put_record(self, trade: dict) -> None:
        self._client.put_record(
            StreamName=KINESIS_STREAM_RAW_TRADES,
            Data=json.dumps(trade).encode("utf-8"),
            PartitionKey=trade["s"],
        )

    async def publish(self, trade: dict) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._put_record, trade)
        except Exception:
            logger.error(
                "Failed to publish trade to Kinesis: symbol=%s", trade.get("s"), exc_info=True
            )
