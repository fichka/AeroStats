from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_PATH = ROOT_DIR / "air_quality_data.csv"
DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"


POLLUTANT_LABELS = {
    "pm25": "PM2.5",
    "pm10": "PM10",
    "pm1": "PM1",
}


def resolve_data_path(path: str | Path | None = None) -> Path:
    return Path(path).resolve() if path else DEFAULT_DATA_PATH


def load_air_quality(path: str | Path | None = None, columns: list[str] | None = None) -> pd.DataFrame:
    data_path = resolve_data_path(path)
    if not data_path.exists():
        raise FileNotFoundError(f"Dataset not found: {data_path}")

    df = pd.read_csv(data_path, usecols=columns)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
        df = df.dropna(subset=["datetime"])
    return df


def load_station_catalog(path: str | Path | None = None) -> pd.DataFrame:
    columns = ["location_id", "name", "lat", "lon", "provider_name"]
    df = load_air_quality(path, columns=columns)
    df = df.dropna(subset=["location_id", "lat", "lon"])
    df["location_id"] = df["location_id"].astype(int)
    catalog = (
        df.drop_duplicates("location_id")
        .sort_values(["provider_name", "name", "location_id"])
        .reset_index(drop=True)
    )
    return catalog


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearest_station(lat: float, lon: float, path: str | Path | None = None) -> dict[str, Any]:
    catalog = load_station_catalog(path)
    distances = catalog.apply(lambda row: haversine_km(lat, lon, row["lat"], row["lon"]), axis=1)
    idx = distances.idxmin()
    row = catalog.loc[idx].to_dict()
    row["distance_km"] = round(float(distances.loc[idx]), 2)
    return row


def choose_training_location(
    path: str | Path | None = None,
    target: str = "pm25",
    location_id: int | None = None,
) -> int:
    columns = ["location_id", target]
    df = load_air_quality(path, columns=columns)
    df[target] = pd.to_numeric(df[target], errors="coerce")
    df = df.dropna(subset=[target, "location_id"])
    df["location_id"] = df["location_id"].astype(int)
    if location_id is not None:
        if location_id not in set(df["location_id"]):
            raise ValueError(f"location_id={location_id} has no usable {target} rows")
        return int(location_id)
    return int(df.groupby("location_id")[target].count().sort_values(ascending=False).index[0])


def station_hourly_series(
    path: str | Path | None,
    location_id: int,
    target: str = "pm25",
    limit_rows: int | None = None,
) -> pd.DataFrame:
    columns = ["datetime", "location_id", target]
    df = load_air_quality(path, columns=columns)
    df["location_id"] = pd.to_numeric(df["location_id"], errors="coerce")
    df[target] = pd.to_numeric(df[target], errors="coerce")
    df = df[(df["location_id"] == location_id) & df[target].notna()]
    df = df[["datetime", target]].sort_values("datetime")
    if limit_rows:
        df = df.tail(limit_rows)
    if df.empty:
        raise ValueError(f"No usable rows for location_id={location_id}, target={target}")

    hourly = (
        df.set_index("datetime")
        .resample("1h")
        .mean(numeric_only=True)
        .interpolate(limit_direction="both")
        .ffill()
        .bfill()
    )
    hourly["hour_sin"] = np.sin(2 * np.pi * hourly.index.hour / 24)
    hourly["hour_cos"] = np.cos(2 * np.pi * hourly.index.hour / 24)
    hourly["dow_sin"] = np.sin(2 * np.pi * hourly.index.dayofweek / 7)
    hourly["dow_cos"] = np.cos(2 * np.pi * hourly.index.dayofweek / 7)
    return hourly


def build_supervised_windows(
    hourly: pd.DataFrame,
    target: str = "pm25",
    history_hours: int = 24,
    horizon_hours: int = 24,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    feature_cols = [target, "hour_sin", "hour_cos", "dow_sin", "dow_cos"]
    values = hourly[feature_cols].to_numpy(dtype=np.float32)
    target_values = hourly[target].to_numpy(dtype=np.float32)
    total = len(hourly) - history_hours - horizon_hours + 1
    if total <= 0:
        raise ValueError("Not enough time points to build supervised windows")

    x = np.zeros((total, history_hours, len(feature_cols)), dtype=np.float32)
    y = np.zeros((total, horizon_hours), dtype=np.float32)
    for i in range(total):
        x[i] = values[i : i + history_hours]
        y[i] = target_values[i + history_hours : i + history_hours + horizon_hours]
    return x, y, feature_cols


def pm25_status(value: float | int | None) -> dict[str, str]:
    if value is None or pd.isna(value):
        return {"level": "unknown", "label": "нет данных", "advice": "Недостаточно данных для рекомендации."}
    value = float(value)
    if value <= 12:
        return {"level": "good", "label": "хороший", "advice": "Можно планировать обычную активность на улице."}
    if value <= 35.4:
        return {"level": "moderate", "label": "умеренный", "advice": "Для большинства людей условия приемлемые."}
    if value <= 55.4:
        return {
            "level": "sensitive",
            "label": "вредный для чувствительных групп",
            "advice": "Людям с чувствительностью к воздуху лучше снизить интенсивные нагрузки.",
        }
    if value <= 150.4:
        return {"level": "unhealthy", "label": "вредный", "advice": "Лучше ограничить длительные прогулки и спорт на улице."}
    return {"level": "hazardous", "label": "опасный", "advice": "Рекомендуется оставаться в помещении и избегать нагрузок на улице."}


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
