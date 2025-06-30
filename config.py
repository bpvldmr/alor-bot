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

# ✅ Проверка, чтобы переменные были установлены
if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, ACCOUNT_ID]):
    raise ValueError("❌ Не найдены переменные окружения: CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, ACCOUNT_ID")

BASE_URL          = "https://api.alor.ru"
INSTRUMENT_GROUP  = "RFUD"  # Срочный рынок (фьючерсы)

# ———————————————————————
# Карта тикеров и параметры торговли
# ———————————————————————

TICKER_MAP = {
    "MOEX:CRU2025": {"trade": "CRU5", "symbol": "CNY-9.25"},
    "MOEX:NGN2025": {"trade": "NGN5", "symbol": "NG-7.25"},
}

START_QTY = {
    "CRU5": 1,
    "NGN5": 1
}

ADD_QTY = {
    "CRU5": 1,
    "NGN5": 1
}

MAX_QTY = {
    "CRU5": 6,
    "NGN5": 2
}
