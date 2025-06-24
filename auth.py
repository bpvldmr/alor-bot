# auth.py
import os
import time
import requests
from loguru import logger

CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCOUNT_ID    = os.getenv("ACCOUNT_ID")
AUTH_URL      = "https://oauth.alor.ru"

_token_cache = None
_token_expires_at = 0

def get_access_token() -> str:
    global _token_cache, _token_expires_at
    if time.time() < _token_expires_at - 30:
        return _token_cache

    url = f"{AUTH_URL}/refresh?token={REFRESH_TOKEN}"
    resp = requests.post(url, timeout=10)
    resp.raise_for_status()
    js = resp.json()

    _token_cache = js["AccessToken"]
    _token_expires_at = time.time() + 25 * 60
    logger.debug("🔑 Access token refreshed")
    return _token_cache
