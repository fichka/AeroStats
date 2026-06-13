from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

API_BASE = os.getenv("AEROSTAT_API_BASE", "http://127.0.0.1:5000").rstrip("/")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4.3")


def api_get(path: str, params: dict[str, Any] | None = None, timeout: int = 20) -> dict[str, Any]:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    with urllib.request.urlopen(f"{API_BASE}{path}{query}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def compact_forecast(location_id: int) -> str:
    try:
        payload = api_get("/api/forecast", {"location_id": location_id})
    except Exception as exc:
        return f"Прогноз недоступен: {exc}"

    values = [float(point["value"]) for point in payload.get("forecast", [])]
    if not values:
        return "Прогноз недоступен: нет точек прогноза."

    peak = max(values)
    avg = sum(values) / len(values)
    peak_point = payload["forecast"][values.index(peak)]
    status = peak_point.get("status", {})
    return (
        f"location_id={location_id}; pollutant={payload.get('target', 'pm25')}; "
        f"horizon={payload.get('horizon_hours', 24)}h; avg={avg:.1f}; peak={peak:.1f}; "
        f"peak_hour={peak_point.get('hour')}; status={status.get('label', 'unknown')}; "
        f"advice={status.get('advice', '')}"
    )


def compact_current(location_id: int) -> str:
    try:
        payload = api_get("/api/current", {"location_id": location_id, "pollutants": "pm25,pm10,pm1"})
    except Exception as exc:
        return f"Live OpenAQ data unavailable: {exc}"

    point = None
    for candidate in payload.get("points", []):
        if int(candidate.get("locationId", -1)) == int(location_id):
            point = candidate
            break
    if point is None and payload.get("points"):
        point = payload["points"][0]
    if not point:
        return "Live OpenAQ data unavailable: no fresh nearby measurements."

    parts = []
    for pollutant, measurement in point.get("measurements", {}).items():
        parts.append(f"{pollutant}={measurement.get('value')} {measurement.get('unit', 'µg/m³')} at {measurement.get('observedAt')}")
    return f"live_station={point.get('name')}; " + "; ".join(parts)


class AerostatAgent:
    def __init__(self) -> None:
        self.client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1") if XAI_API_KEY else None

    async def answer(self, question: str, location_id: int | None) -> str:
        forecast_context = compact_forecast(location_id) if location_id else "Пользователь еще не выбрал станцию."
        current_context = compact_current(location_id) if location_id else "Пользователь еще не выбрал станцию."
        if not self.client:
            return (
                "AI-агент пока не подключен: добавьте XAI_API_KEY в .env. "
                f"Live-контекст: {current_context}. Контекст прогноза: {forecast_context}"
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "Ты AI-ассистент AEROSTAT для мониторинга качества воздуха в Алматы. "
                    "Отвечай кратко, понятно и практически. Если вопрос касается воздуха, используй "
                    "только предоставленный live-контекст и контекст прогноза. Не выдумывай значения. "
                    "Не ставь медицинские диагнозы."
                ),
            },
            {
                "role": "user",
                "content": f"Live-контекст: {current_context}\nКонтекст прогноза: {forecast_context}\n\nВопрос пользователя: {question}",
            },
        ]
        response = self.client.chat.completions.create(model=XAI_MODEL, messages=messages, temperature=0.2)
        return response.choices[0].message.content or "Не удалось сформировать ответ."
