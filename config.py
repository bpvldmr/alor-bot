import os
import time
import httpx

# ——————————————————————————————
#  Переменные окружения
# ——————————————————————————————

CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCOUNT_ID    = os.getenv("ACCOUNT_ID")

# ——————————————————————————————
#  Актуальные базовые URL
# ——————————————————————————————

AUTH_URL = "https://oauth.alor.ru/token"  # ✅ Исправлено!
BASE_URL = "https://api.alor.ru"

# ——————————————————————————————
#  Кеш access_token
# ——————————————————————————————

_token_cache = None
_token_expires_at = 0

def get_access_token() -> str:
    global _token_cache, _token_expires_at

    if time.time() < _token_expires_at - 60:
        return _token_cache

    resp = httpx.post(
        AUTH_URL,  # ✅ Исправлено!
        data={
            "grant_type":    "refresh_token",
            "refresh_token": REFRESH_TOKEN,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded"
        },
        timeout=10
    )

    resp.raise_for_status()
    js = resp.json()

    _token_cache = js["access_token"]
    _token_expires_at = time.time() + js.get("expires_in", 1800)

    return _token_cache

# ——————————————————————————————
#  Баланс (legacy endpoint)
#  https://api.alor.ru/md/v2/Clients/legacy/MOEX/{ACCOUNT_ID}/money
# ——————————————————————————————

def get_current_balance() -> float:
    token = get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/legacy/MOEX/{ACCOUNT_ID}/money?format=Simple"
    headers = {"Authorization": f"Bearer {token}"}

    resp = httpx.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    return float(data.get("free", data.get("cash", 0.0)))

# ——————————————————————————————
#  Портфель (новый endpoint)
#  https://api.alor.ru/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary
# ——————————————————————————————

def get_portfolio_summary(exchange: str = "MOEX") -> dict:
    token = get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/{exchange}/{ACCOUNT_ID}/summary"
    headers = {"Authorization": f"Bearer {token}"}

    resp = httpx.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()

# ——————————————————————————————
#  Карта тикеров и параметры торговли
# ——————————————————————————————

TICKER_MAP = {
    "MOEX:CRU2025": {"trade": "CRU5"},
    "MOEX:NGN2025": {"trade": "NGN5"},
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
