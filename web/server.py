from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, session
from openai import OpenAI
from werkzeug.security import check_password_hash, generate_password_hash

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR / "scripts"))

from data_utils import find_nearest_station, load_air_quality, load_station_catalog, pm25_status
from infer_lstm import predict_forecast
from openaq_client import DEFAULT_LAT, DEFAULT_LIMIT, DEFAULT_LON, DEFAULT_RADIUS_M, get_live_air_quality_with_cache


load_dotenv(ROOT_DIR / ".env")

DATA_PATH = Path(os.getenv("AEROSTAT_DATA_PATH", ROOT_DIR / "air_quality_data.csv")).resolve()
MODEL_DIR = Path(os.getenv("AEROSTAT_MODEL_DIR", ROOT_DIR / "scripts" / "artifacts")).resolve()
DB_PATH = Path(os.getenv("AEROSTAT_WEB_DB", ROOT_DIR / "web" / "aerostat.db")).resolve()

app = Flask(__name__, static_folder=".", static_url_path="")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute(
            """
            create table if not exists users (
                id integer primary key autoincrement,
                email text unique not null,
                password_hash text not null,
                selected_location_id integer,
                created_at timestamp default current_timestamp
            )
            """
        )


def current_user() -> dict[str, Any] | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    with db() as conn:
        row = conn.execute("select id, email, selected_location_id from users where id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def parse_float_arg(name: str, default: float) -> float:
    try:
        return float(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


def parse_int_arg(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def selected_pollutants() -> list[str]:
    raw = request.args.get("pollutants") or request.args.get("targets") or "pm25,pm10,pm1"
    return [item.strip() for item in raw.split(",") if item.strip()]


def station_by_id(location_id: int) -> dict[str, Any] | None:
    catalog = load_station_catalog(DATA_PATH)
    match = catalog[catalog["location_id"] == location_id]
    if match.empty:
        return None
    row = match.iloc[0].to_dict()
    return {
        "location_id": int(row["location_id"]),
        "name": str(row.get("name") or ""),
        "lat": float(row["lat"]),
        "lon": float(row["lon"]),
        "provider_name": str(row.get("provider_name") or ""),
    }


def openaq_error_response(exc: Exception):
    return (
        jsonify(
            {
                "error": "OpenAQ live data unavailable",
                "details": str(exc),
                "hint": "Set OPENAQ_API_KEY in .env and make sure the OpenAQ API is reachable.",
            }
        ),
        502,
    )


def telegram_bot_url() -> str | None:
    username = os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
    if not username:
        return None
    return f"https://t.me/{username}"


def compact_forecast_context(location_id: int) -> str:
    try:
        forecast_payload = predict_forecast(str(DATA_PATH), MODEL_DIR, location_id)
    except Exception as exc:
        forecast_payload = fallback_forecast(location_id)
        forecast_payload["warning"] = str(exc)

    values = [float(point["value"]) for point in forecast_payload.get("forecast", [])]
    if not values:
        return "Forecast unavailable."
    peak = max(values)
    avg = sum(values) / len(values)
    peak_point = forecast_payload["forecast"][values.index(peak)]
    status = peak_point.get("status", {})
    return (
        f"forecast_target={forecast_payload.get('target', 'pm25')}; "
        f"horizon={forecast_payload.get('horizon_hours', 24)}h; "
        f"avg={avg:.1f}; peak={peak:.1f}; peak_at={peak_point.get('datetime')}; "
        f"status={status.get('label', 'unknown')}; advice={status.get('advice', '')}"
    )


def compact_current_context(location_id: int) -> str:
    station = station_by_id(location_id)
    if station is None:
        return "Current data unavailable: unknown station."
    api_key = os.getenv("OPENAQ_API_KEY", "").strip()
    if not api_key:
        return "Current OpenAQ data unavailable: OPENAQ_API_KEY is not configured."
    try:
        live = get_live_air_quality_with_cache(
            api_key,
            latitude=float(station["lat"]),
            longitude=float(station["lon"]),
            radius_m=5_000,
            limit=8,
            pollutants=["pm25", "pm10", "pm1"],
        )
    except Exception as exc:
        return f"Current OpenAQ data unavailable: {exc}"

    point = None
    for candidate in live.get("points", []):
        if int(candidate.get("locationId", -1)) == int(location_id):
            point = candidate
            break
    if point is None and live.get("points"):
        point = live["points"][0]
    if not point:
        return "Current OpenAQ data unavailable: no fresh nearby measurements."

    parts = []
    for pollutant, measurement in point.get("measurements", {}).items():
        parts.append(f"{pollutant}={measurement.get('value')} {measurement.get('unit', 'µg/m³')} at {measurement.get('observedAt')}")
    return f"live_station={point.get('name')}; " + "; ".join(parts)


def ask_xai_agent(question: str, location_id: int | None) -> str:
    xai_key = os.getenv("XAI_API_KEY", "").strip()
    if location_id:
        station = station_by_id(location_id)
        station_context = f"station={station}" if station else f"location_id={location_id}"
        current_context = compact_current_context(location_id)
        forecast_context = compact_forecast_context(location_id)
    else:
        station_context = "No station selected."
        current_context = "No station selected."
        forecast_context = "No station selected."

    if not xai_key:
        return (
            "AI-чат пока не подключен: добавьте XAI_API_KEY в .env. "
            f"Контекст станции: {station_context}. Live: {current_context}. Прогноз: {forecast_context}"
        )

    client = OpenAI(api_key=xai_key, base_url="https://api.x.ai/v1")
    model = os.getenv("XAI_MODEL", "grok-4.3")
    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты AI-ассистент AEROSTAT для качества воздуха в Алматы. "
                    "Отвечай на русском кратко и практически. Используй только переданный контекст "
                    "станции, live-измерений OpenAQ и прогноза. Не выдумывай численные значения. "
                    "Не ставь медицинские диагнозы."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Station context: {station_context}\n"
                    f"Live context: {current_context}\n"
                    f"Forecast context: {forecast_context}\n\n"
                    f"User question: {question}"
                ),
            },
        ],
    )
    return response.choices[0].message.content or "Не удалось сформировать ответ."


def fallback_forecast(location_id: int, target: str = "pm25", hours: int = 24) -> dict[str, Any]:
    columns = ["datetime", "location_id", target]
    df = load_air_quality(DATA_PATH, columns=columns)
    df["location_id"] = pd.to_numeric(df["location_id"], errors="coerce")
    df[target] = pd.to_numeric(df[target], errors="coerce")
    df = df[(df["location_id"] == location_id) & df[target].notna()].sort_values("datetime")
    if df.empty:
        raise ValueError("No recent data for fallback forecast")

    last = df.iloc[-1]
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    points = []
    for i in range(hours):
        value = float(last[target])
        points.append(
            {
                "datetime": (start + timedelta(hours=i)).isoformat(),
                "hour": i + 1,
                "value": round(value, 2),
                "status": pm25_status(value) if target == "pm25" else {},
            }
        )
    return {
        "target": target,
        "location_id": location_id,
        "horizon_hours": hours,
        "model_metrics": None,
        "fallback": True,
        "forecast": points,
    }


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/icon/<path:filename>")
def icon_asset(filename: str):
    return send_from_directory(ROOT_DIR / "icon", filename)


@app.post("/api/register")
def register():
    payload = request.get_json(force=True)
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    if not email or len(password) < 6:
        return jsonify({"error": "Email and password with at least 6 characters are required"}), 400

    try:
        with db() as conn:
            cur = conn.execute(
                "insert into users (email, password_hash) values (?, ?)",
                (email, generate_password_hash(password)),
            )
            session["user_id"] = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"error": "User already exists"}), 409
    return jsonify({"user": current_user()})


@app.post("/api/login")
def login():
    payload = request.get_json(force=True)
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    with db() as conn:
        row = conn.execute("select * from users where email = ?", (email,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401
    session["user_id"] = row["id"]
    return jsonify({"user": current_user()})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
def me():
    return jsonify({"user": current_user()})


@app.get("/api/config")
def config():
    return jsonify({"telegramBotUrl": telegram_bot_url()})


@app.get("/api/stations")
def stations():
    catalog = load_station_catalog(DATA_PATH)
    return jsonify({"stations": catalog.to_dict(orient="records")})


@app.get("/api/nearest-station")
def nearest_station():
    lat = float(request.args["lat"])
    lon = float(request.args["lon"])
    station = find_nearest_station(lat, lon, DATA_PATH)
    user = current_user()
    if user:
        with db() as conn:
            conn.execute(
                "update users set selected_location_id = ? where id = ?",
                (int(station["location_id"]), user["id"]),
            )
    return jsonify({"station": station})


@app.get("/api/live-air-quality")
@app.get("/api/air-quality")
def live_air_quality():
    api_key = os.getenv("OPENAQ_API_KEY", "").strip()
    if not api_key:
        return (
            jsonify(
                {
                    "error": "OPENAQ_API_KEY is not configured",
                    "hint": "Copy .env.example to .env and set OPENAQ_API_KEY.",
                }
            ),
            500,
        )

    lat = max(-90.0, min(parse_float_arg("lat", DEFAULT_LAT), 90.0))
    lon = max(-180.0, min(parse_float_arg("lon", DEFAULT_LON), 180.0))
    radius = parse_int_arg("radius", DEFAULT_RADIUS_M, 1_000, 50_000)
    limit = parse_int_arg("limit", DEFAULT_LIMIT, 1, 30)
    try:
        return jsonify(
            get_live_air_quality_with_cache(
                api_key,
                latitude=lat,
                longitude=lon,
                radius_m=radius,
                limit=limit,
                pollutants=selected_pollutants(),
            )
        )
    except Exception as exc:
        return openaq_error_response(exc)


@app.get("/api/current")
def current_air_quality_for_station():
    location_id = int(request.args["location_id"])
    station = station_by_id(location_id)
    if station is None:
        return jsonify({"error": "Unknown location_id"}), 404

    api_key = os.getenv("OPENAQ_API_KEY", "").strip()
    if not api_key:
        return (
            jsonify(
                {
                    "error": "OPENAQ_API_KEY is not configured",
                    "hint": "Copy .env.example to .env and set OPENAQ_API_KEY.",
                    "station": station,
                }
            ),
            500,
        )

    try:
        payload = get_live_air_quality_with_cache(
            api_key,
            latitude=float(station["lat"]),
            longitude=float(station["lon"]),
            radius_m=parse_int_arg("radius", 5_000, 1_000, 25_000),
            limit=parse_int_arg("limit", 8, 1, 20),
            pollutants=selected_pollutants(),
        )
        payload["selectedStation"] = station
        return jsonify(payload)
    except Exception as exc:
        return openaq_error_response(exc)


@app.get("/api/history")
def history():
    location_id = int(request.args["location_id"])
    target = request.args.get("target", "pm25")
    limit = int(request.args.get("limit", "168"))
    columns = ["datetime", "location_id", target]
    df = load_air_quality(DATA_PATH, columns=columns)
    df["location_id"] = pd.to_numeric(df["location_id"], errors="coerce")
    df[target] = pd.to_numeric(df[target], errors="coerce")
    df = df[(df["location_id"] == location_id) & df[target].notna()].sort_values("datetime").tail(limit)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(hours=max(len(df) - 1, 0))
    rows = [
        {
            "datetime": (start + timedelta(hours=index)).isoformat(),
            "sourceDatetime": row["datetime"].isoformat(),
            "value": round(float(row[target]), 2),
        }
        for index, (_, row) in enumerate(df.iterrows())
    ]
    return jsonify({"target": target, "location_id": location_id, "history": rows})


@app.get("/api/forecast")
def forecast():
    location_id = int(request.args["location_id"])
    try:
        result = predict_forecast(str(DATA_PATH), MODEL_DIR, location_id)
    except Exception as exc:
        result = fallback_forecast(location_id)
        result["warning"] = f"Model forecast unavailable, used persistence fallback: {exc}"
    return jsonify(result)


@app.get("/api/model/metrics")
def model_metrics():
    metadata_path = MODEL_DIR / "metadata.json"
    if not metadata_path.exists():
        return jsonify({"trained": False, "message": "Run scripts/train_lstm.py first"})
    return send_from_directory(MODEL_DIR, "metadata.json")


@app.post("/api/agent/ask")
def agent_ask():
    payload = request.get_json(force=True)
    question = str(payload.get("question", "")).strip()
    location_id_raw = payload.get("location_id")
    location_id = int(location_id_raw) if location_id_raw else None
    if not question:
        return jsonify({"error": "question is required"}), 400
    try:
        return jsonify({"answer": ask_xai_agent(question, location_id)})
    except Exception as exc:
        return jsonify({"error": "AI agent failed", "details": str(exc)}), 502


if __name__ == "__main__":
    init_db()
    debug = os.getenv("AEROSTAT_DEBUG", "0") == "1"
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=debug, use_reloader=False)
