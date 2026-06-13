from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import pandas as pd
from tensorflow.keras.models import load_model

from data_utils import DEFAULT_ARTIFACT_DIR, load_json, pm25_status, station_hourly_series


def predict_forecast(
    data_path: str | None = None,
    artifact_dir: str | Path = DEFAULT_ARTIFACT_DIR,
    location_id: int | None = None,
) -> dict:
    artifact_dir = Path(artifact_dir)
    metadata = load_json(artifact_dir / "metadata.json")
    target = metadata["target"]
    history_hours = int(metadata["history_hours"])
    horizon_hours = int(metadata["horizon_hours"])
    feature_cols = metadata["feature_cols"]
    trained_location_id = int(metadata["location_id"])
    selected_location_id = int(location_id or trained_location_id)

    model = load_model(artifact_dir / "lstm_air_quality.keras")
    x_scaler = joblib.load(artifact_dir / "x_scaler.joblib")
    y_scaler = joblib.load(artifact_dir / "y_scaler.joblib")

    hourly = station_hourly_series(data_path, selected_location_id, target, limit_rows=history_hours * 8)
    window = hourly[feature_cols].tail(history_hours)
    if len(window) < history_hours:
        raise ValueError(f"Need at least {history_hours} hourly rows for inference")

    x = x_scaler.transform(window.to_numpy()).reshape(1, history_hours, len(feature_cols))
    y_scaled = model.predict(x, verbose=0)
    forecast_values = y_scaler.inverse_transform(y_scaled)[0]
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_time = now + timedelta(hours=1)

    points = []
    for i, value in enumerate(forecast_values):
        timestamp = start_time + timedelta(hours=i)
        status = pm25_status(float(value)) if target == "pm25" else {}
        points.append(
            {
                "datetime": pd.Timestamp(timestamp).isoformat(),
                "hour": i + 1,
                "value": round(float(value), 2),
                "status": status,
            }
        )

    return {
        "target": target,
        "location_id": selected_location_id,
        "trained_location_id": trained_location_id,
        "horizon_hours": horizon_hours,
        "model_metrics": {"mae": metadata.get("mae"), "rmse": metadata.get("rmse")},
        "forecast": points,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AEROSTAT LSTM inference.")
    parser.add_argument("--data", default=None)
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--location-id", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = predict_forecast(args.data, args.artifact_dir, args.location_id)
    for point in result["forecast"]:
        print(f"{point['datetime']} {result['target']}={point['value']}")


if __name__ == "__main__":
    main()
