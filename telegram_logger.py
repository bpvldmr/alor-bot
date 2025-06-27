import os
import httpx
from loguru import logger

# Загружаем токен и chat_id из переменных среды
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def send_telegram_log(text: str):
    if not TOKEN or not CHAT_ID:
        logger.warning("⚠️ TELEGRAM_TOKEN или TELEGRAM_CHAT_ID не указаны")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except httpx.RequestError as e:
        logger.error(f"❌ Ошибка сети при отправке Telegram уведомления: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ Ошибка HTTP при отправке Telegram уведомления: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        logger.error(f"❌ Неизвестная ошибка при отправке Telegram уведомления: {e}")
