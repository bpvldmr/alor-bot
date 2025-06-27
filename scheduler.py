from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from auth import get_access_token
from balance import send_balance_to_telegram
import httpx
from loguru import logger
from trading import enable_trading, disable_trading
from config import BASE_URL, ACCOUNT_ID

# 📊 Задача: запрос баланса и отправка в Telegram
async def scheduled_balance_job():
    try:
        token = get_access_token()
        url = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

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
    try:
        logger.info("⏹️ CRON: Отключение торговли")
        await disable_trading()
    except Exception as e:
        logger.exception("❌ Ошибка при отключении торговли")

# ▶️ Включение торговли
async def scheduled_enable_trading():
    try:
        logger.info("▶️ CRON: Включение торговли")
        await enable_trading()
    except Exception as e:
        logger.exception("❌ Ошибка при включении торговли")

# 🔄 Пинг-задача каждые 5 минут — держит Render живым
async def ping_job():
    logger.info("🔄 Ping job is alive (Render keep-alive)")

# ⏱ Планировщик задач
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# ⏰ Ежедневная отправка баланса
scheduler.add_job(scheduled_balance_job, CronTrigger(hour=11, minute=0, day_of_week='mon-fri'), id="morning_balance")
scheduler.add_job(scheduled_balance_job, CronTrigger(hour=18, minute=0, day_of_week='mon-fri'), id="evening_balance")

# ▶️ Включение торговли в 09:00 по будням
scheduler.add_job(scheduled_enable_trading, CronTrigger(hour=9, minute=0, day_of_week='mon-fri'), id="enable_trading")

# ⏹️ Отключение торговли в 23:00 по будням
scheduler.add_job(scheduled_disable_trading, CronTrigger(hour=23, minute=0, day_of_week='mon-fri'), id="disable_trading")

# 🔄 Постоянный ping для Render
scheduler.add_job(ping_job, IntervalTrigger(minutes=5), id="ping_keepalive")
