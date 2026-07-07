import asyncio
import json
import logging
import signal
import time

import boto3
import websockets

from config import (
    AWS_REGION,
    BACKOFF_DELAYS,
    BACKOFF_RESET_SECS,
    FINNHUB_SECRET_NAME,
    FINNHUB_WS_URL,
    SYMBOLS,
    TRADE_STALENESS_MS,
)
from publisher import KinesisPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def _get_api_key() -> str:
    client = boto3.client("secretsmanager", region_name=AWS_REGION)
    return client.get_secret_value(SecretId=FINNHUB_SECRET_NAME)["SecretString"]


def _is_valid(trade: dict) -> bool:
    if trade.get("s") not in SYMBOLS:
        return False
    p = trade.get("p")
    if not p or p <= 0:
        return False
    v = trade.get("v")
    if v is None or v < 0:
        return False
    t = trade.get("t")
    if t is None:
        return False
    if int(time.time() * 1000) - t > TRADE_STALENESS_MS:
        logger.debug("Stale trade discarded: symbol=%s ts=%s", trade.get("s"), t)
        return False
    return True


async def _receive_loop(ws, publisher: KinesisPublisher) -> None:
    async for raw in ws:
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Non-JSON frame discarded")
            continue

        ftype = frame.get("type")

        if ftype == "trade":
            for trade in frame.get("data", []):
                logger.debug("Trade received: %s", trade)
                if _is_valid(trade):
                    asyncio.create_task(
                        publisher.publish(
                            {"s": trade["s"], "p": trade["p"], "v": trade["v"], "t": trade["t"]}
                        )
                    )
        elif ftype == "ping":
            logger.debug("Ping — sending pong")
            await ws.send(json.dumps({"type": "pong"}))
        else:
            logger.debug("Unknown frame type discarded: %s", ftype)


async def _run(api_key: str, publisher: KinesisPublisher, shutdown: asyncio.Event) -> None:
    attempt = 0

    while not shutdown.is_set():
        url = f"{FINNHUB_WS_URL}?token={api_key}"
        connect_time = time.monotonic()

        try:
            logger.info("Connecting to Finnhub (attempt %d)", attempt + 1)
            async with websockets.connect(url) as ws:
                logger.info("Connected. Subscribing to %d symbols.", len(SYMBOLS))
                for symbol in SYMBOLS:
                    await ws.send(json.dumps({"type": "subscribe", "symbol": symbol}))
                await _receive_loop(ws, publisher)

            # receive_loop returned normally — clean close
            elapsed = time.monotonic() - connect_time
            if elapsed >= BACKOFF_RESET_SECS:
                attempt = 0
            logger.info("Clean close after %.0fs. Reconnecting in 5s.", elapsed)
            delay = 5

        except asyncio.CancelledError:
            logger.info("Cancelled — shutting down.")
            return
        except Exception as exc:
            elapsed = time.monotonic() - connect_time
            if elapsed >= BACKOFF_RESET_SECS:
                attempt = 0
            delay = BACKOFF_DELAYS[min(attempt, len(BACKOFF_DELAYS) - 1)]
            attempt += 1
            logger.warning("Disconnected: %s. Reconnecting in %ds.", exc, delay)

        if shutdown.is_set():
            return

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass


async def main() -> None:
    logger.info("Starting mag10-websocket")

    api_key = _get_api_key()
    logger.info("API key loaded from Secrets Manager.")

    publisher = KinesisPublisher()
    shutdown = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown.set)

    await _run(api_key, publisher, shutdown)
    logger.info("mag10-websocket stopped.")


if __name__ == "__main__":
    asyncio.run(main())
