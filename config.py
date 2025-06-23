import os

# === Переменные окружения ===
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCOUNT_ID = os.getenv("ACCOUNT_ID")  # Это портфель (например, "D39004")

# Для баланс-роутера
BASE_URL = "https://api.alor.ru"

# Карта тикеров и параметры стратегии
TICKER_MAP = {
    "MOEX:CRU2025": {"trade": "CRU5"},
    "MOEX:NGN2025": {"trade": "NGN5"},
}
START_QTY = {"CRU5": 4, "NGN5": 1}
MAX_QTY   = {"CRU5": 8, "NGN5": 2}
ADD_QTY   = {"CRU5": 2, "NGN5": 1}
