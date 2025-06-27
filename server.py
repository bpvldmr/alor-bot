import asyncio
import os
from fastapi import FastAPI, Request
from loguru import logger

from webhook import router as webhook_router
from balance import router as balance_router
from auth import get_access_token
from telegram_logger import send_telegram_log
from trading import process_signal


app = FastAPI()

@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"status": "ok", "message": "🚀 Alor bot is running"}

@app.api_route("/healthz", methods=["GET", "HEAD"])
async def health_check():
    return {"status": "healthy"}

# ✅ Подключаем роутеры
app.include_router(webhook_router)
app.include_router(balance_router)

@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Bot started")

    try:
        await send_telegram_log("✅ Бот успешно задеплоен и запущен на Render")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке уведомления в Telegram: {e}")

    try:
        asyncio.create_task(token_refresher())
        logger.info("🔁 Запущен цикл обновления токена")
    except Exception as e:
        logger.error(f"❌ Ошибка запуска token_refresher: {e}")
        try:
            await send_telegram_log(f"❌ Ошибка запуска token_refresher:\n{e}")
        except:
            pass

    try:
        asyncio.create_task(keep_alive())
        logger.info("🔄 Запущен keep_alive для удержания event loop")
    except Exception as e:
        logger.error(f"❌ Ошибка запуска keep_alive: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    logger.warning("🛑 Сервер завершает работу")
    try:
        await send_telegram_log("🛑 Сервер остановлен на Render")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки Telegram-лога при остановке: {e}")

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
        await asyncio.sleep(1500)

async def keep_alive():
    while True:
        await asyncio.sleep(55)

# ✅ Webhook от TradingView
@app.post("/webhook/sEcr0901A2B3")
async def tradingview_webhook(request: Request):
    payload = await request.json()
    tv_tkr = payload.get("signal_ticker")
    sig = payload.get("action")
    token = payload.get("token")

    expected_token = os.getenv("WEBHOOK_TOKEN")

    if expected_token and token != expected_token:
        logger.warning("🚫 Неверный токен вебхука")
        return {"status": "unauthorized"}

    if not tv_tkr or not sig:
        logger.warning("⚠️ Отсутствуют signal_ticker или action")
        return {"status": "invalid payload"}

    try:
        await send_telegram_log(f"📩 TV → Bot:\n{payload}")
        result = await process_signal(tv_tkr, sig)
        logger.info(f"📊 Обработан сигнал {tv_tkr} / {sig}: {result}")
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error(f"❌ Error in signal handler: {e}")
        await send_telegram_log(f"❌ Ошибка при обработке сигнала:\n{e}")
        return {"status": "error", "message": str(e)}
