import argparse
import json
import os

import joblib
import numpy as np
import pandas as pd

FEATURE_COLS = [
    "batch_trade_count", "price_mean", "price_std", "price_min", "price_max",
    "volume_sum", "volume_mean", "volume_max", "price_change_pct",
]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir",  default="/opt/ml/processing/model")
    p.add_argument("--input-dir",  default="/opt/ml/processing/input")
    p.add_argument("--output-dir", default="/opt/ml/processing/output")
    return p.parse_args()


def main():
    args = parse_args()

    model, scaler = joblib.load(os.path.join(args.model_dir, "model.joblib"))
    df = pd.read_csv(os.path.join(args.input_dir, "features.csv"))
    X = df[FEATURE_COLS].values

    raw_scores = model.decision_function(X)
    scores = scaler.transform(raw_scores.reshape(-1, 1)).flatten().clip(0.0, 1.0)

    anomaly_rate = float((scores > 0.5).mean())
    percentiles = np.percentile(scores, [50, 90, 99])

    symbol_rates = {}
    if "symbol" in df.columns:
        for sym, grp in df.groupby("symbol"):
            sym_scores = scores[grp.index]
            symbol_rates[sym] = round(float((sym_scores > 0.5).mean()), 4)

    report = {
        "anomaly_rate": round(anomaly_rate, 4),
        "score_p50":    round(float(percentiles[0]), 4),
        "score_p90":    round(float(percentiles[1]), 4),
        "score_p99":    round(float(percentiles[2]), 4),
        "symbol_anomaly_rates": symbol_rates,
        "n_records": len(scores),
    }

    print(json.dumps(report, indent=2))
    os.makedirs(args.output_dir, exist_ok=True)
    with open(os.path.join(args.output_dir, "evaluation.json"), "w") as f:
        json.dump(report, f, indent=2)

    # ConditionStep reads anomaly_rate to decide whether to register the model
    if not (0.03 <= anomaly_rate <= 0.20):
        print(f"WARNING: anomaly_rate={anomaly_rate} outside [0.03, 0.20] — pipeline will halt")


if __name__ == "__main__":
    main()
