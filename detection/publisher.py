import asyncio
import json
import logging

import boto3

from config import AWS_REGION, KINESIS_STREAM_PROCESSED

logger = logging.getLogger(__name__)


class KinesisPublisher:
    def __init__(self) -> None:
        self._client = boto3.client("kinesis", region_name=AWS_REGION)

    def _put_record(self, signal: dict) -> None:
        self._client.put_record(
            StreamName=KINESIS_STREAM_PROCESSED,
            Data=json.dumps(signal).encode("utf-8"),
            PartitionKey=signal["signal_type"],
        )

    async def publish(self, signal: dict) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._put_record, signal)
        except Exception:
            logger.error(
                "Failed to publish signal: type=%s symbol=%s",
                signal.get("signal_type"),
                signal.get("symbol"),
                exc_info=True,
            )
