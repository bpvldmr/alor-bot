
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from balance import get_balance
import asyncio
from loguru import logger

def start_scheduler():
    scheduler = BackgroundScheduler(timezone="Europe/Moscow")

    # Задача на 11:00
    scheduler.add_job(
        lambda: asyncio.run(get_balance()),
        CronTrigger(hour=11, minute=0),
        name="🕚 Уведомление в 11:00"
    )

    # Задача на 18:00
    scheduler.add_job(
        lambda: asyncio.run(get_balance()),
        CronTrigger(hour=18, minute=0),
        name="🕕 Уведомление в 18:00"
    )

    scheduler.start()
    logger.info("📅 Планировщик уведомлений запущен")
