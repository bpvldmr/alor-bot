
import asyncio
from fastapi import FastAPI
from loguru import logger
from webhook import webhook_router
from balance import balance_router
from auth import get_access_token

app = FastAPI()

# Подключаем ваши маршрутизаторы
app.include_router(webhook_router)
app.include_router(balance_router)


async def refresh_token_loop():
    """
    Фоновая задача: раз в 3300 секунд (~55 минут) тащим новый access_token.
    """
    while True:
        try:
            logger.info("🔁 Обновление access_token…")
            # get_access_token — синхронная, поэтому запускаем в thread-pool
            await asyncio.to_thread(get_access_token)
            logger.info("✅ access_token обновлён")
        except Exception as e:
            logger.error(f"❌ Ошибка обновления access_token: {e}")
        await asyncio.sleep(3300)


@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Запуск приложения")
    # 1) Сразу подтягиваем токен, чтобы не ждать первой итерации
    try:
        await asyncio.to_thread(get_access_token)
        logger.info("✅ access_token получен при старте")
    except Exception as e:
        logger.error(f"❌ Не удалось получить access_token при старте: {e}")

    # 2) Запускаем фоновую задачу
    app.state._refresh_task = asyncio.create_task(refresh_token_loop())


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("🔌 Выключение приложения, останавливаем фоновые задачи")
    task = getattr(app.state, "_refresh_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("🔌 Фоновый цикл обновления токена остановлен")
