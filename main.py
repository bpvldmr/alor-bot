from fastapi import FastAPI, APIRouter, Request
from loguru import logger

app = FastAPI()
webhook_router = APIRouter()

# ✅ Токен, который ты задаёшь для защиты URL
VALID_TOKEN = "sEcr0901A2B3"

@webhook_router.post("/webhook/{token}")
async def webhook(request: Request, token: str):
    if token != VALID_TOKEN:
        logger.warning(f"❌ Неверный токен в URL: {token}")
        return {"error": f"❌ Неверный токен в URL: {token}"}

    try:
        data = await request.json()
        signal_ticker = data.get("signal_ticker")
        action = data.get("action")

        if not signal_ticker or not action:
            return {"error": "Нужно передать signal_ticker и action"}

        result = await process_signal(signal_ticker, action)  # ✅ await для async
        logger.info(f"Сигнал: {signal_ticker}, действие: {action} → {result}")
        return result

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return {"error": str(e)}

# ✅ Включение планировщика при старте FastAPI
@app.on_event("startup")
async def startup_event():
    scheduler.start()
    logger.info("📅 Планировщик задач запущен")

# Регистрируем маршруты
app.include_router(webhook_router)
