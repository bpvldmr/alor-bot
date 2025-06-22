# telegram_logger.py

import requests

TELEGRAM_TOKEN = "7610150119:AAGMzDYUdcI6QQuvt-Vsg8U4s1VSYarLIe0"
TELEGRAM_CHAT_ID = "205721225"

def send_telegram_log(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    response = requests.post(url, data=data)
    if not response.ok:
        print(f"Ошибка отправки в Telegram: {response.text}")
