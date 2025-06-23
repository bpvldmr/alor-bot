import os
import time
import requests
from telegram_logger import send_telegram_log  # Логирование в Telegram

# === ALOR из Render переменных окружения ===
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCOUNT_ID = os.getenv("ACCOUNT_ID")

# === Внутренние переменные токена ===
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

    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    send_telegram_log(f"🔁 access_token обновлён в {timestamp}")

    return _access_token

def get_current_balance():
    url = f"https://api.alor.ru/trade/v2/clients/{ACCOUNT_ID}/summary?exchange=FORTS"
    headers = {
        "Authorization": f"Bearer {get_access_token()}"
    }

    send_telegram_log(f"📤 Запрос баланса ALOR:\n{url}")

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        import json
        send_telegram_log(f"📩 RAW ответ от ALOR:\n{json.dumps(data, indent=2, ensure_ascii=False)}")

        portfolio = data.get("portfolio", {})
        money = data.get("moneySummary", {})

        cash1 = portfolio.get("equity", 0)
        cash2 = money.get("cash", 0)

        send_telegram_log(f"💸 Доступно по equity: {cash1}₽\n💵 Доступно по moneySummary.cash: {cash2}₽")

        return cash1 if cash1 else cash2

    except requests.exceptions.RequestException as e:
        send_telegram_log(f"❌ Ошибка при запросе баланса: {e}")
        return 0

    except Exception as e:
        send_telegram_log(f"⚠️ Ошибка при обработке баланса: {e}")
        return 0


# === Карта тикеров ===
TICKER_MAP = {
    "MOEX:CRU2025": {"trade": "CRU5"},
    "MOEX:NGN2025": {"trade": "NGN5"}
}

# === Параметры стратегии ===
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

# === Telegram логирование ===
TELEGRAM_TOKEN = "7610150119:AAGMzDYUdcI6QQuvt-Vsg8U4s1VSYarLIe0"
TELEGRAM_CHAT_ID = 205721225
