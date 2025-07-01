import os
import time
import asyncio
import httpx
from loguru import logger

BASE_URL = "https://api.alor.ru"
AUTH_URL = "https://oauth.alor.ru"

CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCOUNT_ID    = os.getenv("ACCOUNT_ID")

_token_cache = None
_token_expires_at = 0

async def get_access_token() -> str:
    global _token_cache, _token_expires_at

    if time.time() < _token_expires_at - 30:
        return _token_cache

    url = f"{AUTH_URL}/refresh?token={REFRESH_TOKEN}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url)
        resp.raise_for_status()
        js = resp.json()

    _token_cache = js["AccessToken"]
    _token_expires_at = time.time() + 25 * 60
    logger.debug("🔑 Access token refreshed")
    return _token_cache

async def get_headers() -> dict:
    token = await get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

async def get_current_balance() -> float:
    headers = await get_headers()
    url = f"{BASE_URL}/md/v2/Clients/legacy/MOEX/{ACCOUNT_ID}/money?format=Simple"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    for entry in data.get("money", []):
        if entry.get("currency") in ("RUB", "RUR"):
            return float(entry.get("value", 0.0))

    return float(data.get("free", data.get("cash", 0.0)))
