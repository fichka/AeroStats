from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(Path(__file__).resolve().parent))

try:
    from .agent import AerostatAgent
except ImportError:
    from agent import AerostatAgent


load_dotenv(ROOT_DIR / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
API_BASE = os.getenv("AEROSTAT_API_BASE", "http://127.0.0.1:5000").rstrip("/")
DB_PATH = Path(os.getenv("AEROSTAT_BOT_DB", ROOT_DIR / "telegram_bot" / "telegram_users.db"))

bot = Bot(BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()
agent = AerostatAgent()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute(
            """
            create table if not exists telegram_users (
                id integer primary key autoincrement,
                telegram_chat_id integer unique not null,
                username text,
                user_lat real,
                user_lon real,
                selected_location_id integer,
                selected_station_name text,
                distance_to_station_km real,
                is_subscribed integer default 0,
                alert_threshold_pm25 real default 35.0,
                created_at timestamp default current_timestamp,
                updated_at timestamp default current_timestamp
            )
            """
        )
        conn.execute(
            """
            create table if not exists notifications_log (
                id integer primary key autoincrement,
                telegram_chat_id integer not null,
                location_id integer,
                pollutant text,
                predicted_value real,
                message text,
                sent_at timestamp default current_timestamp
            )
            """
        )


def api_get(path: str, params: dict[str, Any] | None = None, timeout: int = 20) -> dict[str, Any]:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    with urllib.request.urlopen(f"{API_BASE}{path}{query}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_user(chat_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("select * from telegram_users where telegram_chat_id = ?", (chat_id,)).fetchone()
    return dict(row) if row else None


def upsert_user(chat_id: int, username: str | None, **fields: Any) -> None:
    user = get_user(chat_id)
    columns = {"username": username, **fields}
    if user:
        assignments = ", ".join([f"{key} = ?" for key in columns])
        values = list(columns.values()) + [chat_id]
        with db() as conn:
            conn.execute(
                f"update telegram_users set {assignments}, updated_at = current_timestamp where telegram_chat_id = ?",
                values,
            )
        return

    keys = ["telegram_chat_id", *columns.keys()]
    placeholders = ", ".join(["?"] * len(keys))
    values = [chat_id, *columns.values()]
    with db() as conn:
        conn.execute(f"insert into telegram_users ({', '.join(keys)}) values ({placeholders})", values)


def location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить местоположение", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Прогноз"), KeyboardButton(text="Подписаться")],
            [KeyboardButton(text="Настройки"), KeyboardButton(text="Отправить местоположение", request_location=True)],
        ],
        resize_keyboard=True,
    )


async def send_forecast(message: Message) -> None:
    user = get_user(message.chat.id)
    if not user or not user.get("selected_location_id"):
        await message.answer("Сначала отправьте геолокацию, чтобы я нашел ближайшую станцию.", reply_markup=location_keyboard())
        return

    payload = api_get("/api/forecast", {"location_id": int(user["selected_location_id"])})
    values = [float(point["value"]) for point in payload["forecast"]]
    peak = max(values)
    avg = sum(values) / len(values)
    peak_point = payload["forecast"][values.index(peak)]
    status = peak_point.get("status", {})
    await message.answer(
        "\n".join(
            [
                f"Прогноз PM2.5 для станции {user.get('selected_station_name') or user['selected_location_id']}",
                f"Среднее за 24 часа: {avg:.1f} мкг/м³",
                f"Пик: {peak:.1f} мкг/м³ через {peak_point.get('hour')} ч.",
                f"Статус: {status.get('label', 'нет статуса')}",
                status.get("advice", ""),
            ]
        ),
        reply_markup=menu_keyboard(),
    )


@dp.message(Command("start"))
async def start(message: Message) -> None:
    upsert_user(message.chat.id, message.from_user.username if message.from_user else None)
    await message.answer(
        "Привет! Я AEROSTAT. Отправьте геолокацию, чтобы я нашел ближайшую станцию качества воздуха.",
        reply_markup=location_keyboard(),
    )


@dp.message(F.location)
async def handle_location(message: Message) -> None:
    location = message.location
    station = api_get("/api/nearest-station", {"lat": location.latitude, "lon": location.longitude})["station"]
    upsert_user(
        message.chat.id,
        message.from_user.username if message.from_user else None,
        user_lat=location.latitude,
        user_lon=location.longitude,
        selected_location_id=int(station["location_id"]),
        selected_station_name=station.get("name"),
        distance_to_station_km=float(station["distance_km"]),
    )
    await message.answer(
        f"Ближайшая станция: {station.get('name')} · {station.get('provider_name')}\n"
        f"Расстояние: {station['distance_km']} км.\n"
        "Теперь прогнозы и уведомления будут идти по этой точке.",
        reply_markup=menu_keyboard(),
    )
    await send_forecast(message)


@dp.message(Command("forecast"))
@dp.message(F.text.casefold() == "прогноз")
async def forecast(message: Message) -> None:
    await send_forecast(message)


@dp.message(Command("subscribe"))
@dp.message(F.text.casefold() == "подписаться")
async def subscribe(message: Message) -> None:
    upsert_user(message.chat.id, message.from_user.username if message.from_user else None, is_subscribed=1)
    await message.answer("Уведомления включены. По умолчанию предупреждаю при PM2.5 выше 35 мкг/м³.")


@dp.message(Command("unsubscribe"))
async def unsubscribe(message: Message) -> None:
    upsert_user(message.chat.id, message.from_user.username if message.from_user else None, is_subscribed=0)
    await message.answer("Уведомления отключены.")


@dp.message(Command("settings"))
@dp.message(F.text.casefold() == "настройки")
async def settings(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) >= 2:
        try:
            threshold = float(parts[1])
            upsert_user(message.chat.id, message.from_user.username if message.from_user else None, alert_threshold_pm25=threshold)
            await message.answer(f"Порог уведомлений обновлен: PM2.5 > {threshold:g} мкг/м³.")
            return
        except ValueError:
            pass
    user = get_user(message.chat.id)
    threshold = user.get("alert_threshold_pm25", 35) if user else 35
    await message.answer(f"Текущий порог: PM2.5 > {threshold:g} мкг/м³.\nИзменить: /settings 50")


@dp.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "/forecast — прогноз на 24 часа\n"
        "/subscribe — включить уведомления\n"
        "/unsubscribe — отключить уведомления\n"
        "/settings 50 — изменить порог PM2.5\n"
        "Также можно задать вопрос обычным текстом."
    )


@dp.message(F.text)
async def ask_agent(message: Message) -> None:
    user = get_user(message.chat.id)
    location_id = int(user["selected_location_id"]) if user and user.get("selected_location_id") else None
    answer = await agent.answer(message.text or "", location_id)
    await message.answer(answer, reply_markup=menu_keyboard())


async def alert_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        with db() as conn:
            users = conn.execute(
                "select * from telegram_users where is_subscribed = 1 and selected_location_id is not null"
            ).fetchall()
        for row in users:
            user = dict(row)
            try:
                payload = api_get("/api/forecast", {"location_id": int(user["selected_location_id"])})
                values = [float(point["value"]) for point in payload["forecast"]]
                peak = max(values)
                if peak < float(user["alert_threshold_pm25"]):
                    continue
                peak_point = payload["forecast"][values.index(peak)]
                status = peak_point.get("status", {})
                text = (
                    "AEROSTAT Alert\n\n"
                    f"Ожидается PM2.5 до {peak:.1f} мкг/м³ через {peak_point.get('hour')} ч.\n"
                    f"Статус: {status.get('label', 'нет статуса')}.\n"
                    f"{status.get('advice', '')}"
                )
                await bot.send_message(user["telegram_chat_id"], text)
                with db() as conn:
                    conn.execute(
                        "insert into notifications_log (telegram_chat_id, location_id, pollutant, predicted_value, message) values (?, ?, ?, ?, ?)",
                        (user["telegram_chat_id"], user["selected_location_id"], "pm25", peak, text),
                    )
            except Exception as exc:
                print(f"Alert failed for {user['telegram_chat_id']}: {exc}")


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing. Add it to .env.")
    init_db()
    asyncio.create_task(alert_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
