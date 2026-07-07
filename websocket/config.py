import os

SYMBOLS = {"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "AVGO", "PLTR"}

AWS_REGION = os.environ["AWS_REGION"]
KINESIS_STREAM_RAW_TRADES = os.environ["KINESIS_STREAM_RAW_TRADES"]
FINNHUB_SECRET_NAME = os.getenv("FINNHUB_SECRET_NAME", "mag10-finnhub-key")

FINNHUB_WS_URL = "wss://ws.finnhub.io"

# Backoff delays in seconds: 5, 10, 20, 40, 80, then capped at 120
BACKOFF_DELAYS = [5, 10, 20, 40, 80, 120]
# Reset backoff after a connection that stayed open at least this long
BACKOFF_RESET_SECS = 60
# Discard trades older than this
TRADE_STALENESS_MS = 60_000
