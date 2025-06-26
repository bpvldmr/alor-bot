from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from auth import get_access_token
from balance import send_balance_to_telegram
import httpx
from loguru import logger
from trading import enable_trading, disable_trading

BASE_URL = "https://api.alor.ru"
ACCOUNT_ID = "7502QAB"

# 📊 Задача: запрос баланса и отправка в Telegram
async def scheduled_balance_job():
    token = get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
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

# ⏹️ Отключение торговли
async def scheduled_disable_trading():
    await disable_trading()

# ▶️ Включение торговли
async def scheduled_enable_trading():
    await enable_trading()

# ⏱ Планировщик задач
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# Отправка баланса
scheduler.add_job(scheduled_balance_job, CronTrigger(hour=11, minute=0, day_of_week='mon-fri'), id="morning_balance")
scheduler.add_job(scheduled_balance_job, CronTrigger(hour=18, minute=0, day_of_week='mon-fri'), id="evening_balance")

# Включение/отключение торговли
schedu
