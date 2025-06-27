import asyncio
import os
from fastapi import FastAPI
from loguru import logger

from webhook import router as webhook_router
from balance import router as balance_router
from auth import get_access_token
from scheduler import scheduler
from telegram_logger import send_telegram_log

app = FastAPI()

# ✅ Root-эндпоинт с поддержкой HEAD
@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"status": "ok", "message": "🚀 Alor bot is running"}

# ✅ Health Check для Render
@app.api_route("/healthz", methods=["GET", "HEAD"])
async def health_check():
    return {"status": "healthy"}

# ✅ Подключаем роутеры
app.include_router(webhook_router)
app.include_router(balance_router)

# ✅ Стартовое событие
@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Bot started")

    # 🟢 Уведомление в Telegram
    try:
        await send_telegram_log("✅ Бот успешно задеплоен и запущен на Render")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке уведомления в Telegram: {e}")

    # 🔁 Запуск автообновления токена
    try:
        asyncio.create_task(token_refresher())
        logger.info("🔁 Запущен цикл обновления токена")
    except Exception as e:
        logger.error(f"❌ Ошибка запуска token_refresher: {e}")
        try:
            await send_telegram_log(f"❌ Ошибка запуска token_refresher:\n{e}")
        except:
            pass

    # 📅 Запуск планировщика
    try:
        scheduler.start()
        logger.info("📅 Планировщик уведомлений запущен")
        try:
            await send_telegram_log("📅 Планировщик уведомлений запущен")
        except:
            pass
    except Exception as e:
        logger.error(f"❌ Ошибка запуска планировщика: {e}")
        try:
            await send_telegram_log(f"❌ Ошибка запуска планировщика:\n{e}")
        except:
            pass

    # 💡 Поддержка event loop (без уведомлений)
    try:
        asyncio.create_task(keep_alive())
        logger.info("🔄 Запущен keep_alive для удержания event loop")
    except Exception as e:
        logger.error(f"❌ Ошибка запуска keep_alive: {e}")

# ✅ Завершение работы сервера
@app.on_event("shutdown")
async def on_shutdown():
    logger.warning("🛑 Сервер завершает работу")
    try:
        await send_telegram_log("🛑 Сервер остановлен на Render")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки Telegram-лога при остановке: {e}")

# ✅ Цикл автообновления access_token
async def token_refresher():
    while True:
        try:
            get_access_token()
            logger.debug("🔁 Token refreshed")
        except Exception as e:
            logger.error(f"❌ Ошибка обновления токена: {e}")
            try:
                await send_telegram_log(f"❌ Ошибка обновления токена:\n{e}")
            except:
                pass
        await asyncio.sleep(1500)  # ~25 минут

# ✅ Тихий keep_alive (без логов)
async def keep_alive():
    while True:
        await asyncio.sleep(55)
