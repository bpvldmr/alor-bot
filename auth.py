import os
import time
import httpx
from loguru import logger

# ———————————————————————
# Переменные окружения
# ———————————————————————
CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")

BASE_URL = "https://api.alor.ru"

# ———————————————————————
# Кеш токена
# ———————————————————————
_access_token = None
_token_expires_at = 0

async def get_access_token() -> str:
    global _access_token, _token_expires_at

    if _access_token and time.time() < _token_expires_at - 60:
        return _access_token

    url = f"{BASE_URL}/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, data=payload)
        resp.raise_for_status()

    data = resp.json()
    _access_token = data["access_token"]
    _token_expires_at = time.time() + data.get("expires_in", 1800)
    logger.debug("✅ Access token обновлён")
    return _access_token
