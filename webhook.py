from fastapi import APIRouter, Request
from telegram_logger import send_telegram_log
from trading import handle_signal  # Обновлённое имя функции
import json

webhook_router = APIRouter()

SECRET_TOKEN = "sEcr09!@"

@webhook_router.post("/webhook/9f3c7e23da9f49bd84f243acbc2af21a")
async def webhook(request: Request):
    try:
        raw = await request.body()
        text_data = raw.decode("utf-8")

        # Попытка прочитать JSON вручную, чтобы не падало при плохом payload
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError as e:
            send_telegram_log(f"❌ Ошибка парсинга JSON: {e}\n📦 Raw:\n{text_data}")
            return {"status": "invalid json"}

        send_telegram_log(f"📩 Webhook сигнал от TradingView:\n```json\n{text_data}\n```")

        if data.get("token") != SECRET_TOKEN:
            send_telegram_log("❌ Неверный токен в сигнале")
            return {"status": "unauthorized"}

        signal_ticker = data.get("signal_ticker")
        action = data.get("action")

        if not signal_ticker or not action:
            send_telegram_log("⚠️ Ошибка: не хватает signal_ticker или action")
            return {"status": "invalid payload"}

        result = handle_signal(signal_ticker, action.upper())  # LONG / SHORT
        send_telegram_log(f"✅ Обработан сигнал: {signal_ticker} → {action.upper()}\nРезультат: {result}")
        return {"status": "ok", "result": result}

    except Exception as e:
        send_telegram_log(f"❌ Ошибка обработки webhook:\n{str(e)}")
        return {"status": "error", "detail": str(e)}
