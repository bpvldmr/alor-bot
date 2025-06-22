import asyncio
from fastapi import FastAPI
from loguru import logger
from webhook import webhook_router
from balance import balance_router
from auth import get_access_token

app = FastAPI()
app.include_router(webhook_router)
app.include_router(balance_router)

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Запуск приложения")
    asyncio.create_task(refresh_token_loop())

async def refresh_token_loop():
    while True:
        logger.info("🔁 Обновление access_token...")
        try:
            await asyncio.to_thread(get_access_token)
        except Exception as e:
            logger.error(f"❌ Ошибка обновления access_token: {e}")
        await asyncio.sleep(3300)  # ≈55 минут
