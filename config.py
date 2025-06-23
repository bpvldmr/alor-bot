import os
import time
import requests
from telegram_logger import send_telegram_log  # Добавляем логгер Telegram

# === ALOR из окружения Render ===
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCOUNT_ID = os.getenv("ACCOUNT_ID")

# === Внутренние переменные ===
_access_token = None
_access_token_expires = 0

def get_access_token():
    global _access_token, _access_token_expires
    if time.time() < _access_token_expires - 60:
        return _access_token

    url = "https://oauth.alor.ru/token"
    response = requests.post(url, data={
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    })
    response.raise_for_status()
    data = response.json()
    _access_token = data["access_token"]
    _access_token_expires = time.time() + data["expires_in"]

    # 🟢 Telegram лог об обновлении
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    send_telegram_log(f"🔁 access_token обновлён в {timestamp}")

    return _access_token

# === Тикеры ===
TICKER_MAP = {
    "MOEX:CRU2025": {"trade": "CRU5"},
    "MOEX:NGN2025": {"trade": "NGN5"}
}

# === Параметры торговли ===
START_QTY = {
    "CRU5": 4,
    "NGN5": 1
}
MAX_QTY = {
    "CRU5": 8,
    "NGN5": 2
}
ADD_QTY = {
    "CRU5": 2,
    "NGN5": 1
}

# === Telegram (оставляем фиксировано) ===
TELEGRAM_TOKEN = "7610150119:AAGMzDYUdcI6QQuvt-Vsg8U4s1VSYarLIe0"
TELEGRAM_CHAT_ID = 205721225
