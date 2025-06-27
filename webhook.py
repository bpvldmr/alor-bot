from fastapi import APIRouter, Request
import json
from telegram_logger import send_telegram_log
from trading import handle_trading_signal as process_signal


router = APIRouter()

# 🔐 Убедись, что он совпадает с TradingView URL
SECRET_TOKEN = "sEcr0901A2B3"

@router.post("/webhook/{token}")
async def webhook(token: str, request: Request):
    # ✅ Безопасность: защита от символов переноса, пробелов и пустых токенов
    token = token.strip()
    if not token or token != SECRET_TOKEN:
        await send_telegram_log(f"❌ Неверный токен в URL: `{token}`")
        return {"status": "unauthorized"}

    # ✅ Чтение и очистка тела запроса
    try:
        raw = (await request.body()).decode("utf-8").strip()
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        await send_telegram_log(f"❌ JSON decode error: {e}\nRaw: {raw}")
        return {"status": "invalid json"}
    except Exception as e:
        await send_telegram_log(f"❌ Unexpected error while parsing body: {e}")
        return {"status": "error", "message": str(e)}

    await send_telegram_log(f"📩 TV → Bot:\n```json\n{raw}\n```")

    # ✅ Валидация
    action = data.get("action", "").strip().upper()
    ticker = data.get("signal_ticker", "").strip()

    if not action or not ticker:
        await send_telegram_log("⚠️ Invalid payload: missing 'action' or 'signal_ticker'")
        return {"status": "invalid payload"}

    try:
        result = await handle_trading_signal(ticker, action)
        await send_telegram_log(f"🔔 Result: {result}")
        return {"status": "ok", "result": result}
    except Exception as e:
        await send_telegram_log(f"❌ Error in signal handler: {e}")
        return {"status": "error", "message": str(e)}
