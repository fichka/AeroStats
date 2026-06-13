from __future__ import annotations

import json
import os
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


OPENAQ_BASE = os.getenv("OPENAQ_BASE", "https://api.openaq.org/v3")
DEFAULT_LAT = 43.238949
DEFAULT_LON = 76.889709
DEFAULT_RADIUS_M = 25_000
DEFAULT_LIMIT = 12
MAX_OBS_AGE_HOURS = 48
CACHE_TTL_SECONDS = 180

PARAMETER_IDS = {
    "pm10": 1,
    "pm25": 2,
    "pm2.5": 2,
}

POLLUTANT_ALIASES = {
    "pm2.5": "pm25",
    "pm25": "pm25",
    "pm10": "pm10",
    "pm1": "pm1",
}

_cache: dict[str, Any] = {"key": None, "expires_at": 0.0, "payload": None}
_cache_lock = threading.Lock()


def to_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_pollutant(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("_", "").replace(" ", "")
    return POLLUTANT_ALIASES.get(raw, raw)


def build_ssl_context() -> ssl.SSLContext:
    if os.getenv("AEROSTAT_SKIP_SSL_VERIFY", "").strip().lower() in {"1", "true", "yes"}:
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def fetch_openaq(path: str, api_key: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = urlencode(params or {}, doseq=True)
    url = f"{OPENAQ_BASE}{path}"
    if query:
        url = f"{url}?{query}"

    request = Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "X-API-Key": api_key},
    )
    with urlopen(request, timeout=25, context=build_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_parameter_name(row: dict[str, Any]) -> str:
    parameter = row.get("parameter")
    if isinstance(parameter, dict):
        return normalize_pollutant(parameter.get("name") or parameter.get("displayName"))
    return normalize_pollutant(parameter)


def extract_sensor_id(row: dict[str, Any]) -> int | None:
    for key in ("sensorsId", "sensorId", "sensor_id", "sensors_id", "id"):
        sensor_id = to_int(row.get(key))
        if sensor_id is not None:
            return sensor_id
    return None


def extract_sensor_parameter(sensor: dict[str, Any]) -> tuple[str, int | None]:
    parameter = sensor.get("parameter")
    if isinstance(parameter, dict):
        return normalize_pollutant(parameter.get("name") or parameter.get("displayName")), to_int(parameter.get("id"))
    return normalize_pollutant(parameter), to_int(sensor.get("parametersId") or sensor.get("parameterId"))


def parse_observed_at(row: dict[str, Any]) -> str | None:
    datetime_payload = row.get("datetime")
    if isinstance(datetime_payload, dict):
        local = datetime_payload.get("local")
        if isinstance(local, str) and local:
            return local
        utc = datetime_payload.get("utc")
        if isinstance(utc, str) and utc:
            return utc
    for key in ("date", "datetimeUtc", "datetimeLocal"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def is_recent_observation(observed_at: str | None, max_age_hours: int = MAX_OBS_AGE_HOURS) -> bool:
    if not observed_at:
        return False
    candidate = observed_at.replace("Z", "+00:00") if observed_at.endswith("Z") else observed_at
    try:
        measured_at = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - measured_at.astimezone(timezone.utc)).total_seconds()
    return age_seconds <= max_age_hours * 3600


def fetch_locations_near_coords(
    api_key: str,
    *,
    latitude: float,
    longitude: float,
    radius_m: int,
    limit: int,
    primary_pollutant: str = "pm25",
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "coordinates": f"{latitude},{longitude}",
        "radius": str(radius_m),
        "limit": "100",
        "page": "1",
    }
    parameter_id = PARAMETER_IDS.get(normalize_pollutant(primary_pollutant))
    if parameter_id is not None:
        params["parameters_id"] = str(parameter_id)

    data = fetch_openaq("/locations", api_key, params)
    results = data.get("results")
    if not isinstance(results, list):
        return []

    candidates: list[dict[str, Any]] = []
    for location in results:
        if not isinstance(location, dict):
            continue
        coordinates = location.get("coordinates")
        if not isinstance(coordinates, dict):
            continue
        lat = to_float(coordinates.get("latitude"))
        lon = to_float(coordinates.get("longitude"))
        if lat is None or lon is None:
            continue
        candidates.append(location)

    candidates.sort(key=lambda item: float(item.get("distance") or 1e12))
    return candidates[:limit]


def fetch_latest_measurements(
    api_key: str,
    location: dict[str, Any],
    pollutants: set[str],
) -> dict[str, Any] | None:
    location_id = to_int(location.get("id"))
    if location_id is None:
        return None

    latest = fetch_openaq(f"/locations/{location_id}/latest", api_key, {"limit": "100"})
    rows = latest.get("results")
    if not isinstance(rows, list):
        return None

    coordinates = location.get("coordinates")
    if not isinstance(coordinates, dict):
        return None
    lat = to_float(coordinates.get("latitude"))
    lon = to_float(coordinates.get("longitude"))
    if lat is None or lon is None:
        return None

    measurements: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        pollutant = extract_parameter_name(row)
        if pollutant not in pollutants:
            continue
        value = to_float(row.get("value"))
        observed_at = parse_observed_at(row)
        if value is None or value < 0 or not is_recent_observation(observed_at):
            continue
        measurements[pollutant] = {
            "value": round(float(value), 2),
            "unit": row.get("unit") or "µg/m³",
            "observedAt": observed_at,
            "sensorId": extract_sensor_id(row),
        }

    if not measurements:
        return None

    return {
        "id": f"openaq-{location_id}",
        "locationId": location_id,
        "name": str(location.get("name") or f"Location {location_id}"),
        "lat": lat,
        "lon": lon,
        "distanceMeters": to_float(location.get("distance")),
        "measurements": measurements,
    }


def build_live_air_quality_snapshot(
    api_key: str,
    *,
    latitude: float,
    longitude: float,
    radius_m: int = DEFAULT_RADIUS_M,
    limit: int = DEFAULT_LIMIT,
    pollutants: list[str] | None = None,
) -> dict[str, Any]:
    normalized_pollutants = {normalize_pollutant(item) for item in (pollutants or ["pm25", "pm10", "pm1"])}
    normalized_pollutants.discard("")
    if not normalized_pollutants:
        normalized_pollutants = {"pm25"}

    locations = fetch_locations_near_coords(
        api_key,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        limit=limit,
        primary_pollutant="pm25" if "pm25" in normalized_pollutants else next(iter(normalized_pollutants)),
    )

    points: list[dict[str, Any]] = []
    if locations:
        with ThreadPoolExecutor(max_workers=min(8, len(locations))) as executor:
            futures = [executor.submit(fetch_latest_measurements, api_key, location, normalized_pollutants) for location in locations]
            for future in as_completed(futures):
                try:
                    point = future.result()
                except (HTTPError, URLError, TimeoutError):
                    point = None
                if point is not None:
                    points.append(point)

    points.sort(
        key=lambda item: item.get("measurements", {}).get("pm25", {}).get("value", -1),
        reverse=True,
    )
    return {
        "provider": "openaq",
        "source": "live",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "city": {"name": "Almaty", "lat": latitude, "lon": longitude},
        "pollutants": sorted(normalized_pollutants),
        "points": points,
    }


def get_live_air_quality_with_cache(
    api_key: str,
    *,
    latitude: float,
    longitude: float,
    radius_m: int = DEFAULT_RADIUS_M,
    limit: int = DEFAULT_LIMIT,
    pollutants: list[str] | None = None,
) -> dict[str, Any]:
    pollutant_key = ",".join(sorted(normalize_pollutant(item) for item in (pollutants or ["pm25", "pm10", "pm1"])))
    cache_key = f"{round(latitude, 4)}:{round(longitude, 4)}:{radius_m}:{limit}:{pollutant_key}"
    now = time.time()
    with _cache_lock:
        if (
            _cache.get("key") == cache_key
            and isinstance(_cache.get("payload"), dict)
            and float(_cache.get("expires_at") or 0.0) > now
        ):
            return _cache["payload"]

    payload = build_live_air_quality_snapshot(
        api_key,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        limit=limit,
        pollutants=pollutants,
    )
    with _cache_lock:
        _cache["key"] = cache_key
        _cache["expires_at"] = now + CACHE_TTL_SECONDS
        _cache["payload"] = payload
    return payload
