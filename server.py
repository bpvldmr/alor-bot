import asyncio
from fastapi import FastAPI
from loguru import logger
from webhook import webhook_router
from auth import get_access_token

app = FastAPI()
app.include_router(webhook_router)

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Запуск приложения")
    asyncio.create_task(refresh_token_loop())  # 🔄 Запускаем цикл обновления токена

async def refresh_token_loop():
    while True:
        logger.info("🔁 Обновление access_token...")
        get_access_token()
        await asyncio.sleep(3300)  # Обновляем каждые ~55 минут
