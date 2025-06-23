from fastapi import APIRouter, Request
from telegram_logger import send_telegram_log
from trading import handle_trading_signal

webhook_router = APIRouter()

SECRET_TOKEN = "sEcr09!@"

@webhook_router.post("/webhook/9f3c7e23da9f49bd84f243acbc2af21a")
async def webhook(request: Request):
    try:
        # Чтение "сырых" данных
        raw_data = await request.body()
        text_data = raw_data.decode("utf-8")

        send_telegram_log(f"📩 Получен сигнал от TradingView:\n```json\n{text_data}\n```")

        data = await request.json()

        if data.get("token") != SECRET_TOKEN:
            send_telegram_log("❌ Неверный токен в сигнале TradingView")
            return {"status": "unauthorized"}

        signal_ticker = data.get("signal_ticker")
        action = data.get("action")

        if not signal_ticker or not action:
            send_telegram_log("⚠️ Ошибка: signal_ticker или action отсутствует")
            return {"status": "invalid payload"}

        await handle_trading_signal(signal_ticker, action)
        send_telegram_log(f"✅ Обработан сигнал: {signal_ticker} → {action}")
        return {"status": "ok"}

    except Exception as e:
        send_telegram_log(f"❌ Ошибка обработки webhook: {e}")
        return {"status": "error", "detail": str(e)}
