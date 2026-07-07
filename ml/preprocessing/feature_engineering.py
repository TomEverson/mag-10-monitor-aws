import argparse
import gzip
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--input-path",  default="/opt/ml/processing/input")
    p.add_argument("--output-path", default="/opt/ml/processing/output")
    p.add_argument("--lookback-days", type=int, default=14)
    p.add_argument("--val-days",      type=int, default=2)
    return p.parse_args()


def main():
    args = parse_args()
    cutoff_ms = _days_ago_ms(args.lookback_days)
    val_cutoff_ms = _days_ago_ms(args.val_days)

    # Collect all trades from bronze NDJSON files
    trades: list[dict] = []
    for root, _, files in os.walk(args.input_path):
        for fname in files:
            path = os.path.join(root, fname)
            try:
                trades.extend(_read_file(path, cutoff_ms))
            except Exception as exc:
                print(f"Warning: skipping {path}: {exc}")

    if not trades:
        raise RuntimeError("No trades found in input path")

    print(f"Loaded {len(trades)} trades")

    # Group by (symbol, 5-minute window bucket)
    from collections import defaultdict
    windows: dict[tuple, list[dict]] = defaultdict(list)
    for t in trades:
        symbol = t["s"]
        bucket = t["t"] // (5 * 60 * 1000)  # 5-minute bucket
        windows[(symbol, bucket)].append(t)

    train_rows: list[str] = []
    val_rows: list[str] = []
    header = "symbol,event_time,batch_trade_count,price_mean,price_std,price_min,price_max,volume_sum,volume_mean,volume_max,price_change_pct\n"

    for (symbol, bucket), bucket_trades in windows.items():
        row = _compute_row(symbol, bucket_trades)
        max_ts = max(t["t"] for t in bucket_trades)
        if max_ts >= val_cutoff_ms:
            val_rows.append(row)
        else:
            train_rows.append(row)

    out = Path(args.output_path)
    (out / "train").mkdir(parents=True, exist_ok=True)
    (out / "validation").mkdir(parents=True, exist_ok=True)

    _write_csv(out / "train" / "features.csv", header, train_rows)
    _write_csv(out / "validation" / "features.csv", header, val_rows)

    print(f"Train rows: {len(train_rows)}, Validation rows: {len(val_rows)}")


def _compute_row(symbol: str, trades: list[dict]) -> str:
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
    return (
        f"{symbol},{event_time},{n},{mean_p},{std_p},"
        f"{min(prices)},{max(prices)},{vol_sum},{vol_sum / n},{max(volumes)},{pct_change}\n"
    )


def _read_file(path: str, cutoff_ms: int) -> list[dict]:
    if path.endswith(".gz"):
        with gzip.open(path, "rt") as f:
            lines = f.readlines()
    else:
        with open(path) as f:
            lines = f.readlines()
    trades = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        t = json.loads(line)
        if t.get("t", 0) >= cutoff_ms:
            trades.append(t)
    return trades


def _days_ago_ms(days: int) -> int:
    from datetime import timedelta
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return int(dt.timestamp() * 1000)


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    with open(path, "w") as f:
        f.write(header)
        f.writelines(rows)


if __name__ == "__main__":
    main()
