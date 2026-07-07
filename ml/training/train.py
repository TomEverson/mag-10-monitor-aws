import argparse
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import MinMaxScaler

FEATURE_COLS = [
    "batch_trade_count", "price_mean", "price_std", "price_min", "price_max",
    "volume_sum", "volume_mean", "volume_max", "price_change_pct",
]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir",     default="/opt/ml/input/data/train")
    p.add_argument("--model-dir",     default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
    p.add_argument("--n_estimators",  type=int,   default=200)
    p.add_argument("--contamination", type=float, default=0.1)
    p.add_argument("--random_state",  type=int,   default=42)
    return p.parse_args()


def main():
    args = parse_args()

    df = pd.read_csv(os.path.join(args.input_dir, "features.csv"))
    X = df[FEATURE_COLS].values
    print(f"Training on {len(X)} rows, {len(FEATURE_COLS)} features")

    model = IsolationForest(
        n_estimators=args.n_estimators,
        contamination=args.contamination,
        random_state=args.random_state,
    )
    model.fit(X)

    # Fit scaler on training decision scores to normalise to [0, 1]
    raw_scores = model.decision_function(X)
    scaler = MinMaxScaler()
    scaler.fit(raw_scores.reshape(-1, 1))

    # Verify normalisation: clipped scores should be in [0, 1]
    normalised = scaler.transform(raw_scores.reshape(-1, 1)).flatten()
    print(f"Score range after normalisation: [{normalised.min():.3f}, {normalised.max():.3f}]")

    os.makedirs(args.model_dir, exist_ok=True)
    joblib.dump((model, scaler), os.path.join(args.model_dir, "model.joblib"))
    print("Model saved.")


if __name__ == "__main__":
    main()
