import asyncio
from fastapi import FastAPI
from loguru import logger

from webhook import router as webhook_router
from balance import router as balance_router
from auth import get_access_token
from scheduler import scheduler
from telegram_logger import send_telegram_log  # ✅ добавим лог в телегу

app = FastAPI()

# ✅ Root-эндпоинт для проверки
@app.get("/")
async def root():
    return {"status": "ok", "message": "🚀 Alor bot is running"}

# ✅ Подключение всех роутеров
app.include_router(webhook_router)
app.include_router(balance_router)

# ✅ Событие при старте сервера
@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Bot started")
    await send_telegram_log("🚀 Бот запущен на Render")

    try:
        asyncio.create_task(token_refresher())
        logger.info("🔁 Запущен цикл обновления токена")
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске token_refresher: {e}")

    scheduler.start()
    logger.info("📅 Планировщик уведомлений запущен")

# ✅ Событие при завершении сервера
@app.on_event("shutdown")
async def on_shutdown():
    logger.warning("🛑 Сервер завершает работу")
    await send_telegram_log("🛑 Сервер остановлен Render")

# ✅ Цикл автообновления access_token
async def token_refresher():
    while True:
        try:
            get_access_token()
            logger.debug("🔁 Token refreshed")
        except Exception as e:
            logger.error(f"❌ Ошибка обновления токена: {e}")
        await asyncio.sleep(1500)  # 25 минут
