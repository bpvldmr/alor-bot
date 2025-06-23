import os
import time
import requests

# ------------------------------------------------------------------------------
# === Параметры из окружения ===
# ------------------------------------------------------------------------------
ACCOUNT_ID    = os.getenv("ACCOUNT_ID")    # пример: "7502QAB"
CLIENT_ID     = os.getenv("CLIENT_ID")     # из Render ENV
CLIENT_SECRET = os.getenv("CLIENT_SECRET") # из Render ENV
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN") # из Render ENV
REDIRECT_URI  = os.getenv("REDIRECT_URI", "https://oauth.alor.ru/blank.html")

# ------------------------------------------------------------------------------
# === Кэш для access_token ===
# ------------------------------------------------------------------------------
_access_token         = None
_access_token_expires = 0  # UNIX timestamp

def get_access_token() -> str:
    """
    Возвращает валидный access_token.
    Если токен ещё не истёк, берём из кэша, иначе делаем POST на OAuth refresh.
    """
    global _access_token, _access_token_expires

    # если в течение 60 сек до истечения ещё годится
    if _access_token and time.time() < _access_token_expires - 60:
        return _access_token

    url = "https://oauth.alor.ru/refresh"
    # тело по spec Alor: { "token": "<REFRESH_TOKEN>" }
    payload = {"token": REFRESH_TOKEN}
    # Basic auth не требуется, но если понадобится, можно добавить auth=(CLIENT_ID, CLIENT_SECRET)
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    # в разных версиях API поле может называться чуть по-разному
    token = data.get("access_token") or data.get("AccessToken") or data.get("token")
    expires_in = data.get("expires_in", 1800)  # дефолт 30 мин

    _access_token = token
    _access_token_expires = time.time() + expires_in
    return _access_token

# ------------------------------------------------------------------------------
# === Запрос баланса по FORTS «legacy» контуру ===
# ------------------------------------------------------------------------------
def get_current_balance() -> float:
    """
    Запрашивает текущий баланс (RUB) по счёту FORTS
    через legacy-эндпоинт:
      GET https://api.alor.ru/md/v2/Clients/legacy/MOEX/{ACCOUNT_ID}/money
    """
    token = get_access_token()
    url = f"https://api.alor.ru/md/v2/Clients/legacy/MOEX/{ACCOUNT_ID}/money"
    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    # Ищем элемент с валютой RUB/RUR
    for entry in data.get("money", []):
        if entry.get("currency") in ("RUB", "RUR"):
            return float(entry.get("value", 0))
    return 0.0

# ------------------------------------------------------------------------------
# === Ваши торговые тикеры и параметры ===
# ------------------------------------------------------------------------------
TICKER_MAP = {
    "MOEX:CRU2025": {"trade": "CRU5"},
    "MOEX:NGN2025": {"trade": "NGN5"},
}

START_QTY = {
    "CRU5": 5,
    "NGN5": 3,
}

MAX_QTY = {
    "CRU5": 9,
    "NGN5": 5,
}

ADD_QTY = {
    "CRU5": 2,
    "NGN5": 1,
}
