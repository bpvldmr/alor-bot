from fastapi import APIRouter, Request
import json
from telegram_logger import send_telegram_log
from trading import handle_trading_signal

router = APIRouter()  # <-- теперь называется именно `router` (а не webhook_router)
SECRET_TOKEN = "sEcr0901A2B3"  # ← новый простой токен

@router.post("/webhook/{token}")
async def webhook(token: str, request: Request):
    # 1) Проверяем токен из URL
    if token != SECRET_TOKEN:
        send_telegram_log(f"❌ Неверный токен в URL: {token}")
        return {"status": "unauthorized"}

    # 2) Читаем тело
    raw = (await request.body()).decode("utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        send_telegram_log(f"❌ JSON decode error: {e}\nRaw: {raw}")
        return {"status": "invalid json"}

    send_telegram_log(f"📩 TV → Bot:\n```json\n{raw}\n```")

    # 3) Валидируем payload
    action = data.get("action")
    ticker = data.get("signal_ticker")
    if not action or not ticker:
        send_telegram_log("⚠️ Invalid payload: missing 'action' or 'signal_ticker'")
        return {"status": "invalid payload"}

    # 4) Обрабатываем сигнал
    result = await handle_trading_signal(ticker, action.upper())
    send_telegram_log(f"🔔 Result: {result}")

    return {"status": "ok", "result": result}
