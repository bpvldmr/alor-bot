import os
import time
import requests
from loguru import logger

CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCOUNT_ID    = os.getenv("ACCOUNT_ID")

BASE_URL = "https://api.alor.ru"
AUTH_URL = "https://oauth.alor.ru"

# Кеш токена
_token_cache = None
_token_expires_at = 0  # Временная метка истечения токена

def get_access_token() -> str:
    global _token_cache, _token_expires_at

    # Повторно используем токен, если ещё не истёк
    if time.time() < _token_expires_at - 30:  # буфер на всякий случай
        return _token_cache

    try:
        url = f"{AUTH_URL}/refresh?token={REFRESH_TOKEN}"
        response = requests.post(url, timeout=10)
        response.raise_for_status()
        js = response.json()
        _token_cache = js["AccessToken"]
        _token_expires_at = time.time() + 25 * 60  # автообновление каждые 25 минут

        logger.debug("🔑 Access token refreshed")
        return _token_cache

    except Exception as e:
        logger.error(f"❌ Token refresh error: {e}")
        raise

def get_current_balance() -> float:
    token = get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/legacy/MOEX/{ACCOUNT_ID}/money?format=Simple"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    for entry in data.get("money", []):
        if entry.get("currency") in ("RUB", "RUR"):
            return float(entry.get("value", 0.0))

    return float(data.get("free", data.get("cash", 0.0)))
