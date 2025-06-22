import requests
import time

# === Настройки ALOR API ===
CLIENT_ID = "93e214f3a9e74524a075"
CLIENT_SECRET = "TmAUmTAz6JJbhLZZguRzoP3p5dJ9RUrvlAzz19Y9U0U="
REFRESH_TOKEN = "a0facbb9-aadd-4f67-88e0-1204dcd392b5"

ACCOUNT_ID = "7502QAB"

_access_token = None
_access_token_expires = 0

def get_access_token():
    global _access_token, _access_token_expires
    if time.time() < _access_token_expires - 60:
        return _access_token

    url = "https://api.alor.ru/refresh"
    response = requests.post(url, data={
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    })
    response.raise_for_status()
    data = response.json()
    _access_token = data["access_token"]
    _access_token_expires = time.time() + data["expires_in"]
    return _access_token

# === Соответствие тикеров TradingView и тикеров Alor ===
TICKER_MAP = {
    "MOEX:CRU2025": {"trade": "CRU5"},
    "MOEX:NGN2025": {"trade": "NGN5"}
}

# === Параметры торговли ===
START_QTY = {
    "CRU5": 5,
    "NGN5": 3
}

MAX_QTY = {
    "CRU5": 9,
    "NGN5": 5
}

ADD_QTY = {
    "CRU5": 2,
    "NGN5": 1
}

# === Настройки Telegram ===
TELEGRAM_TOKEN = "7610150119:AAGMzDYUdcI6QQuvt-Vsg8U4s1VSYarLIe0"
TELEGRAM_CHAT_ID = 205721225
