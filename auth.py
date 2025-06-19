import os
import requests
from loguru import logger

# ✅ Берём переменные из окружения Render
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
REDIRECT_URI = os.getenv("REDIRECT_URI")

ACCESS_TOKEN = None

def get_access_token():
    global ACCESS_TOKEN
    url = "https://oauth.alor.ru/refresh"
    payload = {
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "refresh_token"
    }

    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            ACCESS_TOKEN = response.json().get("access_token")
            logger.info("✅ Access token успешно обновлён.")
        else:
            logger.error(f"❌ Ошибка получения токена: {response.text}")
            ACCESS_TOKEN = None
    except Exception as e:
        logger.exception(f"⚠️ Ошибка соединения: {e}")
        ACCESS_TOKEN = None

    return ACCESS_TOKEN
