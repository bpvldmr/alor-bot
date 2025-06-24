import os
import time
import httpx
from loguru import logger

CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCOUNT_ID    = os.getenv("ACCOUNT_ID")

BASE_URL = "https://api.alor.ru"

# Кеш токена
_token_cache      = None
_token_expires_at = 0

def get_access_token() -> str:
    global _token_cache, _token_expires_at
    if time.time() < _token_expires_at - 60:
        return _token_cache

    resp = httpx.post(
        f"{BASE_URL}/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": REFRESH_TOKEN,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET
        },
        timeout=10
    )
    resp.raise_for_status()
    js = resp.json()
    _token_cache      = js["access_token"]
    _token_expires_at = time.time() + js.get("expires_in", 1800)
    logger.debug("🔑 Access token refreshed")
    return _token_cache

# ✅ Добавляем сюда эту функцию
def get_current_balance() -> float:
    token = get_access_token()
    url   = f"{BASE_URL}/md/v2/Clients/legacy/MOEX/{ACCOUNT_ID}/money?format=Simple"
    headers = {"Authorization": f"Bearer {token}"}
    resp = httpx.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    # Ищем валюту RUB в списке money
    for entry in data.get("money", []):
        if entry.get("currency") in ("RUB", "RUR"):
            return float(entry.get("value", 0.0))
    
    # Fallback
    return float(data.get("free", data.get("cash", 0.0)))
