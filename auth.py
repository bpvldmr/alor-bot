import os
import time
import httpx
from loguru import logger
from config import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN

# Кэш токена
_access_token = None
_expiry = 0

async def get_access_token() -> str:
    global _access_token, _expiry
    # Если токен ещё действителен — возвращаем
    if _access_token and time.time() < _expiry - 60:
        return _access_token

    url = "https://oauth.alor.ru/token"
    payload = {
        "grant_type":    "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, data=payload)
        resp.raise_for_status()

    data = resp.json()
    _access_token = data["access_token"]
    _expiry = time.time() + data.get("expires_in", 1800)
    logger.debug("✅ Access token обновлён")
    return _access_token
