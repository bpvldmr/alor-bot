import asyncio
from fastapi import FastAPI
from loguru import logger

# Правильно импортируем наши роутеры
from webhook import webhook_router
from balance import balance_router  # если в balance.py ваш роутер называется balance_router

from auth import get_access_token

app = FastAPI()

# Подключаем маршруты
app.include_router(webhook_router)
app.include_router(balance_router)

@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Bot started")
    # Запускаем фоновый таск по обновлению токена
    asyncio.create_task(_token_refresher())

async def _token_refresher():
    while True:
        try:
            # Вызываем синхронный get_access_token в отдельном потоке
            await asyncio.to_thread(get_access_token)
            logger.debug("🔁 Token refreshed")
        except Exception as e:
            logger.error(f"❌ Refresh error: {e}")
        # Ждём примерно 55 минут
        await asyncio.sleep(3300)
