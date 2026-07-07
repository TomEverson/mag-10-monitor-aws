import asyncio
import json
import logging
import signal
import threading
import time

import boto3

import ml_scorer
import warm_start
from config import (
    AWS_REGION,
    KINESIS_STREAM_RAW_TRADES,
    SECTOR_SNAPSHOT_INTERVAL_SECS,
)
from detectors.momentum import MomentumDetector
from detectors.sector import SectorDetector
from detectors.volatility import VolatilityDetector
from detectors.volume import VolumeDetector
from publisher import KinesisPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kinesis setup
# ---------------------------------------------------------------------------

def _stream_info(kinesis) -> tuple[str, str]:
    """Returns (stream_arn, shard_id)."""
    desc = kinesis.describe_stream_summary(StreamName=KINESIS_STREAM_RAW_TRADES)
    arn = desc["StreamDescriptionSummary"]["StreamARN"]
    shard_id = kinesis.list_shards(StreamName=KINESIS_STREAM_RAW_TRADES)["Shards"][0]["ShardId"]
    return arn, shard_id


def _register_consumer(kinesis, stream_arn: str) -> str:
    """Register EFO consumer and block until ACTIVE. Returns consumer ARN."""
    resp = kinesis.register_stream_consumer(
        StreamARN=stream_arn,
        ConsumerName="mag10-detection-consumer",
    )
    consumer_arn = resp["Consumer"]["ConsumerARN"]
    logger.info("EFO consumer registered: %s", consumer_arn)

    while True:
        status = kinesis.describe_stream_consumer(ConsumerARN=consumer_arn)[
            "ConsumerDescription"
        ]["ConsumerStatus"]
        if status == "ACTIVE":
            break
        logger.info("Waiting for EFO consumer to become ACTIVE (status=%s)…", status)
        time.sleep(2)

    logger.info("EFO consumer is ACTIVE.")
    return consumer_arn


# ---------------------------------------------------------------------------
# Kinesis consumer thread — bridges blocking subscribe_to_shard into asyncio
# ---------------------------------------------------------------------------

def _kinesis_thread(
    loop: asyncio.AbstractEventLoop,
    kinesis,
    consumer_arn: str,
    shard_id: str,
    queue: asyncio.Queue,
    shutdown: threading.Event,
    continuation: dict,      # {"sn": str | None} — mutable so caller sees updates
) -> None:
    starting = (
        {"Type": "AT_SEQUENCE_NUMBER", "SequenceNumber": continuation["sn"]}
        if continuation["sn"]
        else {"Type": "LATEST"}
    )

    try:
        response = kinesis.subscribe_to_shard(
            ConsumerARN=consumer_arn,
            ShardId=shard_id,
            StartingPosition=starting,
        )
        for event in response["EventStream"]:
            if shutdown.is_set():
                break
            if "SubscribeToShardEvent" not in event:
                continue
            shard_event = event["SubscribeToShardEvent"]
            continuation["sn"] = shard_event.get("ContinuationSequenceNumber")
            for record in shard_event.get("Records", []):
                try:
                    trade = json.loads(record["Data"])
                    asyncio.run_coroutine_threadsafe(queue.put(trade), loop)
                except Exception:
                    logger.warning("Failed to parse Kinesis record", exc_info=True)
    except Exception as exc:
        logger.warning("Kinesis shard stream ended: %s", exc)


# ---------------------------------------------------------------------------
# Async coroutines
# ---------------------------------------------------------------------------

async def _consume_loop(
    kinesis,
    consumer_arn: str,
    shard_id: str,
    queue: asyncio.Queue,
    shutdown_async: asyncio.Event,
    shutdown_thread: threading.Event,
    continuation: dict,
) -> None:
    loop = asyncio.get_running_loop()

    while not shutdown_async.is_set():
        future = loop.run_in_executor(
            None,
            _kinesis_thread,
            loop, kinesis, consumer_arn, shard_id, queue, shutdown_thread, continuation,
        )
        try:
            await future
        except Exception as exc:
            logger.warning("Consumer thread error: %s", exc)

        if not shutdown_async.is_set():
            logger.info("Shard stream ended — resubscribing in 2s.")
            await asyncio.sleep(2)


async def _process_trades(
    queue: asyncio.Queue,
    detectors: list,
    sector_detector: SectorDetector,
    publisher: KinesisPublisher,
    shutdown: asyncio.Event,
) -> None:
    all_detectors = detectors + [sector_detector]

    while not shutdown.is_set():
        try:
            trade = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        logger.debug("Trade: symbol=%s price=%s", trade.get("s"), trade.get("p"))
        ml_scorer.update(trade)

        for detector in all_detectors:
            sig = detector.process(trade)
            if sig is not None:
                sig["ml_anomaly_score"] = await ml_scorer.score(trade["s"])
                asyncio.create_task(publisher.publish(sig))
                logger.info("Signal fired: %s %s", sig["signal_type"], sig.get("symbol", ""))


async def _sector_loop(
    sector_detector: SectorDetector,
    publisher: KinesisPublisher,
    shutdown: asyncio.Event,
) -> None:
    while not shutdown.is_set():
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=SECTOR_SNAPSHOT_INTERVAL_SECS)
        except asyncio.TimeoutError:
            pass
        if shutdown.is_set():
            break
        snapshot = sector_detector.get_snapshot()
        asyncio.create_task(publisher.publish(snapshot))
        logger.debug("Sector snapshot published.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    logger.info("Starting mag10-detection")

    kinesis = boto3.client("kinesis", region_name=AWS_REGION)

    volume_det = VolumeDetector()
    momentum_det = MomentumDetector()
    volatility_det = VolatilityDetector()
    sector_det = SectorDetector()
    detectors = [volume_det, momentum_det, volatility_det]

    logger.info("Running warm-start…")
    warm_start.run([volume_det, momentum_det, volatility_det, sector_det])

    stream_arn, shard_id = _stream_info(kinesis)
    consumer_arn = _register_consumer(kinesis, stream_arn)

    publisher = KinesisPublisher()
    trade_queue: asyncio.Queue = asyncio.Queue()
    shutdown_async = asyncio.Event()
    shutdown_thread = threading.Event()
    continuation: dict = {"sn": None}

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: (shutdown_async.set(), shutdown_thread.set()))

    await asyncio.gather(
        _consume_loop(kinesis, consumer_arn, shard_id, trade_queue, shutdown_async, shutdown_thread, continuation),
        _process_trades(trade_queue, detectors, sector_det, publisher, shutdown_async),
        _sector_loop(sector_det, publisher, shutdown_async),
    )

    logger.info("mag10-detection stopped.")


if __name__ == "__main__":
    asyncio.run(main())
