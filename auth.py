import requests
from loguru import logger

REFRESH_TOKEN = "a0facbb9-aadd-4f67-88e0-1204dcd392b5"
CLIENT_ID = "93e214f3a9e74524a075"
CLIENT_SECRET = "TmAUmTAz6JJbhLZZguRzoP3p5dJ9RUrvlAzz19Y9U0U="
REDIRECT_URI = "https://oauth.alor.ru/blank.html"

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
