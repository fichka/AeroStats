from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.callbacks import EarlyStopping
from tensorflow.keras.layers import LSTM, Dense, Dropout, Input
from tensorflow.keras.models import Sequential

from data_utils import (
    DEFAULT_ARTIFACT_DIR,
    build_supervised_windows,
    choose_training_location,
    save_json,
    station_hourly_series,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a small AEROSTAT LSTM model.")
    parser.add_argument("--data", default=None, help="Path to air_quality_data.csv")
    parser.add_argument("--target", default="pm25", choices=["pm25", "pm10", "pm1"])
    parser.add_argument("--location-id", type=int, default=None)
    parser.add_argument("--history-hours", type=int, default=24)
    parser.add_argument("--horizon-hours", type=int, default=24)
    parser.add_argument("--limit-rows", type=int, default=25000)
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--output-dir", default=str(DEFAULT_ARTIFACT_DIR))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    location_id = choose_training_location(args.data, args.target, args.location_id)
    hourly = station_hourly_series(args.data, location_id, args.target, args.limit_rows)
    x, y, feature_cols = build_supervised_windows(
        hourly,
        target=args.target,
        history_hours=args.history_hours,
        horizon_hours=args.horizon_hours,
    )

    split = int(len(x) * 0.8)
    x_train_raw, x_test_raw = x[:split], x[split:]
    y_train_raw, y_test_raw = y[:split], y[split:]

    x_scaler = MinMaxScaler()
    y_scaler = MinMaxScaler()
    x_train = x_scaler.fit_transform(x_train_raw.reshape(-1, x.shape[-1])).reshape(x_train_raw.shape)
    x_test = x_scaler.transform(x_test_raw.reshape(-1, x.shape[-1])).reshape(x_test_raw.shape)
    y_train = y_scaler.fit_transform(y_train_raw)
    y_test = y_scaler.transform(y_test_raw)

    model = Sequential(
        [
            Input(shape=(args.history_hours, len(feature_cols))),
            LSTM(32),
            Dropout(0.15),
            Dense(32, activation="relu"),
            Dense(args.horizon_hours),
        ]
    )
    model.compile(optimizer="adam", loss="mse")
    model.fit(
        x_train,
        y_train,
        validation_split=0.15,
        epochs=args.epochs,
        batch_size=args.batch_size,
        callbacks=[EarlyStopping(monitor="val_loss", patience=2, restore_best_weights=True)],
        verbose=1,
    )

    pred_scaled = model.predict(x_test, verbose=0)
    pred = y_scaler.inverse_transform(pred_scaled)
    rmse = float(np.sqrt(mean_squared_error(y_test_raw.reshape(-1), pred.reshape(-1))))
    mae = float(mean_absolute_error(y_test_raw.reshape(-1), pred.reshape(-1)))

    model_path = output_dir / "lstm_air_quality.keras"
    x_scaler_path = output_dir / "x_scaler.joblib"
    y_scaler_path = output_dir / "y_scaler.joblib"
    metadata_path = output_dir / "metadata.json"

    model.save(model_path)
    joblib.dump(x_scaler, x_scaler_path)
    joblib.dump(y_scaler, y_scaler_path)
    save_json(
        metadata_path,
        {
            "target": args.target,
            "location_id": location_id,
            "history_hours": args.history_hours,
            "horizon_hours": args.horizon_hours,
            "feature_cols": feature_cols,
            "rows_used": int(len(hourly)),
            "train_windows": int(len(x_train)),
            "test_windows": int(len(x_test)),
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
        },
    )

    print(f"Saved model: {model_path}")
    print(f"Saved scalers: {x_scaler_path}, {y_scaler_path}")
    print(f"Metrics: MAE={mae:.3f}, RMSE={rmse:.3f}")


if __name__ == "__main__":
    main()
