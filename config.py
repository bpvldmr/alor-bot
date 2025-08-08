# ✅ Файл: config.py
# Проект полностью перешёл на работу с биржевыми символами:
#   • CNY-9.25  (фьючерс CNY/RUB SEP-25)
#   • NG-8.25   (фьючерс Natural Gas )

import os
from dotenv import load_dotenv

load_dotenv()  # Подгружаем переменные из .env

CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCOUNT_ID    = os.getenv("ACCOUNT_ID")

if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, ACCOUNT_ID]):
    raise ValueError(
        "❌ Не найдены переменные окружения: "
        "CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, ACCOUNT_ID"
    )

BASE_URL         = "https://api.alor.ru"
INSTRUMENT_GROUP = "RFUD"

# --- соответствие TradingView → ALOR ---------------------------------------
TICKER_MAP = {
    "MOEX:CRU2025": {            # TradingView-тикер юаневого фьючерса
        "trade":  "CNY-9.25",    # внутренний ключ = биржевой symbol
        "symbol": "CNY-9.25"     # то же значение уходит в ALOR-API
    },
    "MOEX:NGQ2025": {            # TradingView-тикер газового фьючерса
        "trade":  "NG-8.25",
        "symbol": "NG-8.25"
    }
}

# --- объёмы для бота --------------------------------------------------------
START_QTY = { "CNY-9.25": 5, "NG-8.25": 7 }
ADD_QTY   = { "CNY-9.25":  5, "NG-8.25": 1 }
MAX_QTY   = { "CNY-9.25": 15, "NG-8.25": 10 }
