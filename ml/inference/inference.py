import json
import os

import joblib
import numpy as np


def model_fn(model_dir: str):
    return joblib.load(os.path.join(model_dir, "model.joblib"))


def input_fn(request_body: str, content_type: str) -> np.ndarray:
    if content_type != "application/json":
        raise ValueError(f"Unsupported content type: {content_type}")
    data = json.loads(request_body)
    return np.array(data["features"], dtype=float)


def predict_fn(input_data: np.ndarray, model) -> list[float]:
    iso_forest, scaler = model
    raw_scores = iso_forest.decision_function(input_data)
    normalised = scaler.transform(raw_scores.reshape(-1, 1)).flatten()
    return normalised.clip(0.0, 1.0).tolist()


def output_fn(prediction: list[float], accept: str) -> tuple[str, str]:
    return json.dumps({"scores": prediction}), "application/json"
