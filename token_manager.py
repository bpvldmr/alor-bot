import httpx
from config import ALOR_CLIENT_ID, ALOR_CLIENT_SECRET, ALOR_REFRESH_TOKEN
from loguru import logger

access_token = None

async def update_access_token():
    global access_token
    try:
        response = httpx.post(
            "https://oauth.alor.ru/refresh",
            data={
                "refresh_token": ALOR_REFRESH_TOKEN,
                "client_id": ALOR_CLIENT_ID,
                "client_secret": ALOR_CLIENT_SECRET
            }
        )
        response.raise_for_status()
        access_token = response.json()["access_token"]
        logger.info("Access token успешно обновлён.")
    except Exception as e:
        logger.error(f"Ошибка при обновлении токена: {e}")
