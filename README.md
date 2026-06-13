# AEROSTAT

SmartScape Hackathon 2026, Track 2: Ecology & Urban Environment.

AEROSTAT forecasts air quality in Almaty for the next 24 hours using historical OpenAQ data from the Kaggle dataset `Historical Air Quality Measurements: Almaty, KZ`.

## Structure

```text
scripts/
  data_utils.py       Shared dataset, station, distance, and status helpers
  train_lstm.py      Trains a small LSTM model
  infer_lstm.py      Runs forecast inference from saved artifacts
  artifacts/         Saved model, scalers, and metadata

web/
  server.py          Flask API and static site server
  index.html         React CDN shell
  app.jsx            React dashboard, auth modals, map, charts, and chat
  styles.css         Website styles

telegram_bot/
  bot.py             Telegram bot with geolocation, forecasts, and alerts
  agent.py           xAI/Grok-powered AI answer module
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## How to Fill `.env`

Create a local `.env` file from the example:

```bash
copy .env.example .env
```

Open `.env` and fill it step by step.

### 1. Local Project Settings

These values can usually stay unchanged:

```env
AEROSTAT_DATA_PATH=air_quality_data.csv
AEROSTAT_MODEL_DIR=scripts/artifacts
AEROSTAT_API_BASE=http://127.0.0.1:5000
```

Use another path only if the CSV dataset, model artifacts, or API server are moved.

### 2. Flask Secret Key

Set any long random string. It is used for website sessions:

```env
FLASK_SECRET_KEY=replace-with-random-secret
```

Example generation command:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. OpenAQ API Key

Required for live air-quality data from OpenAQ:

```env
OPENAQ_API_KEY=your-openaq-api-key
```

Steps:

1. Create or open your OpenAQ account.
2. Generate an API key in the OpenAQ dashboard.
3. Paste the key after `OPENAQ_API_KEY=`.

If your local network has SSL certificate issues, keep this as `0` by default:

```env
AEROSTAT_SKIP_SSL_VERIFY=0
```

Set it to `1` only for local debugging when HTTPS certificate verification blocks OpenAQ requests.

### 4. Telegram Bot Token

Required only if you want to run the Telegram bot:

```env
TELEGRAM_BOT_TOKEN=...
```

Steps:

1. Open Telegram.
2. Find `@BotFather`.
3. Send `/newbot`.
4. Choose a bot name and username.
5. Copy the token from BotFather.
6. Paste it into `.env`:

```env
TELEGRAM_BOT_TOKEN=1234567890:telegram-token-here
TELEGRAM_BOT_USERNAME=your_bot_username
```

`TELEGRAM_BOT_USERNAME` is the public username without `@`. It is used only to build the dashboard button link, for example `https://t.me/your_bot_username`.

### 5. xAI / Grok API Key

Required only for AI-agent answers in the Telegram bot:

```env
XAI_API_KEY=...
XAI_MODEL=grok-4.3
```

Steps:

1. Open the xAI developer console.
2. Create an API key.
3. Paste it after `XAI_API_KEY=`.
4. Keep `XAI_MODEL=grok-4.3` unless you want to use another available xAI model.

`XAI_API_KEY` is optional for the menu/forecast bot. Without it, forecasts and alerts still work, but free-form AI answers return a setup message.

### Final `.env` Example

```env
AEROSTAT_DATA_PATH=air_quality_data.csv
AEROSTAT_MODEL_DIR=scripts/artifacts
AEROSTAT_API_BASE=http://127.0.0.1:5000
FLASK_SECRET_KEY=replace-with-random-secret
OPENAQ_API_KEY=your-openaq-api-key
AEROSTAT_SKIP_SSL_VERIFY=0
TELEGRAM_BOT_TOKEN=1234567890:telegram-token-here
TELEGRAM_BOT_USERNAME=your_bot_username
XAI_API_KEY=xai-your-key-here
XAI_MODEL=grok-4.3
```

Do not commit `.env`. It contains private API keys and bot tokens.

## Train a Small LSTM

```bash
python scripts/train_lstm.py --target pm25 --epochs 3 --limit-rows 12000
```

Artifacts are saved to:

```text
scripts/artifacts/lstm_air_quality.keras
scripts/artifacts/x_scaler.joblib
scripts/artifacts/y_scaler.joblib
scripts/artifacts/metadata.json
```

## Run Inference

```bash
python scripts/infer_lstm.py
```

## Run Website and API

```bash
python web/server.py
```

Open:

```text
http://127.0.0.1:5000
```

If the LSTM model has not been trained yet, `/api/forecast` uses a persistence fallback based on the latest observed value.

Website flow:

1. Main page shows a public landing page with project information.
2. User opens a separate login or registration modal.
3. After login, the dashboard opens.
4. Dashboard tabs include nearest station, OpenStreetMap station map, AI chat, and Telegram bot link.
5. The nearest-station flow uses browser geolocation and then loads live OpenAQ data, historical chart, and 24-hour forecast.
6. Charts include time labels on the x-axis.
7. The AI chat receives selected station, current OpenAQ context, and LSTM forecast context.

Frontend note:

```text
The UI is written in React in web/app.jsx.
React, Babel, and Leaflet are loaded from CDN for hackathon-speed development.
Forecast timestamps are always generated from the current date/time.
Historical chart points are displayed as the latest hours relative to the current date/time.
```

Useful API endpoints:

```text
GET /api/stations
GET /api/nearest-station?lat=...&lon=...
GET /api/current?location_id=...
GET /api/live-air-quality?lat=...&lon=...
GET /api/history?location_id=...
GET /api/forecast?location_id=...
POST /api/agent/ask
```

## Run Telegram Bot

Start the website/API first, then:

```bash
python telegram_bot/bot.py
```

Bot flow:

1. User sends `/start`.
2. Bot asks for geolocation.
3. Backend finds the nearest air-quality station.
4. Bot shows the 24-hour PM2.5 forecast.
5. User can subscribe to Telegram alerts.
6. User can ask natural-language questions answered by xAI/Grok with forecast context.
