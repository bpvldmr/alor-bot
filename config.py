import os
from dotenv import load_dotenv

load_dotenv()  # Подгружаем переменные из .env

# ———————————————————————
# Константы авторизации и API
# ———————————————————————

CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCOUNT_ID    = os.getenv("ACCOUNT_ID")

ALOR_BASE_URL     = "https://api.alor.ru"
INSTRUMENT_GROUP  = "FUT"  # Срочный рынок (фьючерсы)

# ———————————————————————
# Карта тикеров и параметры торговли
# ———————————————————————

TICKER_MAP = {
    "MOEX:CRU2025": {"trade": "CRU5"},  # фьючерс на CNY/RUB
    "MOEX:NGN2025": {"trade": "NGN5"},  # фьючерс на газ
}

START_QTY = {
    "CRU5": 5,
    "NGN5": 3
}

ADD_QTY = {
    "CRU5": 2,
    "NGN5": 1
}

MAX_QTY = {
    "CRU5": 9,
    "NGN5": 5
}
