import httpx
import os

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT  = os.getenv("TELEGRAM_CHAT_ID")

async def send_telegram_log(text:str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload={"chat_id":CHAT,"text":text,"parse_mode":"Markdown"}
    try:
        await httpx.post(url, json=payload, timeout=5)
    except Exception:
        pass
