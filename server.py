# server.py
import asyncio
from fastapi import FastAPI
from loguru import logger
from webhook import router as webhook_router
from balance import router as balance_router
from auth import get_access_token  # ✅ sync-функция из auth.py

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from balance import send_balance_to_telegram
import httpx

app = FastAPI()

# Подключение роутеров
app.include_router(webhook_router)
app.include_router(balance_router)

BASE_URL = "https://api.alor.ru"
ACCOUNT_ID = "7502QAB"

# 🕒 Задача по расписанию: отправка баланса
async def scheduled_balance_job():
    token = get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/{ACCOUNT_ID}/summary"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.debug(f"📊 [CRON] Ответ от Alor: {data}")
            await send_balance_to_telegram(data)
    except Exception as e:
        logger.exception("❌ Ошибка при автоотправке баланса в Telegram")

# ⏱ Планировщик задач
def start_scheduler():
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(scheduled_balance_job, CronTrigger(hour=11, minute=0))
    scheduler.add_job(scheduled_balance_job, CronTrigger(hour=18, minute=0))
    scheduler.start()
    logger.info("📅 Планировщик уведомлений запущен")

@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Bot started")
    asyncio.create_task(token_refresher())
    start_scheduler()

# ♻️ Автообновление токена
async def token_refresher():
    while True:
        try:
            get_access_token()  # ✅ sync
            logger.debug("🔁 Token refreshed")
        except Exception as e:
            logger.error(f"❌ Refresh error: {e}")
        await asyncio.sleep(1500)  # 25 минут
