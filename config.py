# ✅ Файл: config.py
# Изменения:
# - Заменены все CRU5 на CNY-9.25
# - Заменены все NGN5 на NG-7.25

import os
from dotenv import load_dotenv

load_dotenv()  # Подгружаем переменные из .env

CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCOUNT_ID    = os.getenv("ACCOUNT_ID")

if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, ACCOUNT_ID]):
    raise ValueError("❌ Не найдены переменные окружения: CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, ACCOUNT_ID")

BASE_URL          = "https://api.alor.ru"
INSTRUMENT_GROUP  = "RFUD"

TICKER_MAP = {
    "MOEX:CRU2025": {"trade": "CNY-9.25", "symbol": "CNY-9.25"},
    "MOEX:NGN2025": {"trade": "NG-7.25", "symbol": "NG-7.25"},
}

START_QTY = {
    "CNY-9.25": 20,
    "NG-7.25": 2
}

ADD_QTY = {
    "CNY-9.25": 2,
    "NG-7.25": 1
}

MAX_QTY = {
    "CNY-9.25": 24,
    "NG-7.25": 2
}
