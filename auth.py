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
    # Если ещё валиден — возвращаем
    if _access_token and time.time() < _expiry - 60:
        return _access_token

    # По инструкции OAuth2 Alor:
    url = "https://oauth.alor.ru/token"
    payload = {
        "grant_type":    "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    resp = httpx.post(url, data=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    _access_token = data["access_token"]
    _expiry = time.time() + data["expires_in"]
    logger.debug("✅ Access token обновлён")
    return _access_token
