# auth.py
# Обновлено: добавлена retry-логика (до 3 попыток, пауза 5 с) для обновления AccessToken

import os
import time
import asyncio
import httpx
from loguru import logger

BASE_URL  = "https://api.alor.ru"
AUTH_URL  = "https://oauth.alor.ru"

CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCOUNT_ID    = os.getenv("ACCOUNT_ID")

# ─────────────────────────── кэш токена ──────────────────────────────────────
_token_cache: str | None = None
_token_expires_at: float = 0.0
_refresh_lock = asyncio.Lock()          # защищаем одновременный refresh

# ─────────────────────────── основная функция ───────────────────────────────
async def get_access_token() -> str:
    """
    Возвращает действующий Bearer-token.
    • Если кэш валиден (до истечения >30 с) — берёт из памяти.
    • Иначе делает запрос https://oauth.alor.ru/refresh?token=…
      с повтором до 3 раз (только при сетевых и 5xx-ошибках).
    """
    global _token_cache, _token_expires_at

    if _token_cache and time.time() < _token_expires_at - 30:
        return _token_cache

    async with _refresh_lock:                       # одиночный refresh
        if _token_cache and time.time() < _token_expires_at - 30:
            return _token_cache                    # мог обновиться в ожидании lock

        url = f"{AUTH_URL}/refresh?token={REFRESH_TOKEN}"

        for attempt in (1, 2, 3):                  # до 3 попыток
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(url)
                    resp.raise_for_status()
                    js = resp.json()

                _token_cache      = js["AccessToken"]
                _token_expires_at = time.time() + 25 * 60   # запас 25 мин
                logger.debug("🔑 Access token refreshed")
                return _token_cache

            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                logger.warning(f"OAuth HTTP {code} (try {attempt}/3)")
                if code < 500:                     # 4xx → фатальная ошибка
                    raise
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                logger.warning(f"OAuth network error [{e}] (try {attempt}/3)")
            except Exception as e:
                logger.error(f"Unexpected token refresh error: {e}")
                raise

            if attempt < 3:
                await asyncio.sleep(5)             # 5 с пауза перед повторами

        raise RuntimeError("Не удалось обновить AccessToken после 3 попыток")

# ─────────────────────────── хелперы ─────────────────────────────────────────
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
