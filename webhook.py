from fastapi import APIRouter, Request
import json
from telegram_logger import send_telegram_log
from trading import process_signal  # ✅ Обработка сигналов
from auth import get_current_balance

router = APIRouter()

# 🔐 Секретный токен из TradingView webhook URL
SECRET_TOKEN = "sEcr0901A2B3"

@router.post("/webhook/{token}")
async def webhook(token: str, request: Request):
    token = token.strip()
    if token != SECRET_TOKEN:
        await send_telegram_log(f"❌ Неверный токен в URL: `{token}`")
        return {"status": "unauthorized"}

    try:
        raw_body = await request.body()
        if not raw_body:
            await send_telegram_log("⚠️ Пустое тело запроса")
            return {"status": "empty body"}

        raw = raw_body.decode("utf-8").strip()
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        await send_telegram_log(f"❌ JSON decode error: {e}\nRaw: {raw}")
        return {"status": "invalid json"}
    except Exception as e:
        await send_telegram_log(f"❌ Unexpected error while parsing body: {e}")
        return {"status": "error", "message": str(e)}

    await send_telegram_log(f"📩 TV → Bot:\n```json\n{raw}\n```")

    action = data.get("action", "").strip().upper()
    ticker = data.get("signal_ticker", "").strip()

    if not action or not ticker:
        await send_telegram_log("⚠️ Invalid payload: отсутствует 'action' или 'signal_ticker'")
        return {"status": "invalid payload"}

    try:
        result = await process_signal(ticker, action)
        await send_telegram_log(f"🔔 Результат обработки: {result}")
        return {"status": "ok", "result": result}

    except Exception as e:
        try:
            balance = await get_current_balance()
            await send_telegram_log(
                f"❌ Ошибка в обработчике сигнала: {e}\n📊 Баланс: {balance:.2f} ₽"
            )
        except Exception as be:
            await send_telegram_log(
                f"❌ Ошибка в обработчике сигнала: {e}\n⚠️ И ошибка при получении баланса: {be}"
            )
        return {"status": "error", "message": str(e)}
