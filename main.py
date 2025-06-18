from fastapi import APIRouter, Request
from trading import process_signal
from loguru import logger

webhook_router = APIRouter()

@webhook_router.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        signal_ticker = data.get("signal_ticker")
        action = data.get("action")

        if not signal_ticker or not action:
            return {"error": "Нужно передать signal_ticker и action"}

        result = process_signal(signal_ticker, action)
        logger.info(f"Сигнал: {signal_ticker}, действие: {action} → {result}")
        return result

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return {"error": str(e)}
