from fastapi import APIRouter, Request
import json
from telegram_logger import send_telegram_log
from trading import handle_trading_signal

router = APIRouter()
SECRET_TOKEN = "sEcr0901A2B3"  # Убедись, что он совпадает с TradingView URL

@router.post("/webhook/{token}")
async def webhook(token: str, request: Request):
    if token != SECRET_TOKEN:
        await send_telegram_log(f"❌ Неверный токен в URL: {token}")
        return {"status": "unauthorized"}

    raw = (await request.body()).decode("utf-8").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        await send_telegram_log(f"❌ JSON decode error: {e}\nRaw: {raw}")
        return {"status": "invalid json"}

    await send_telegram_log(f"📩 TV → Bot:\n```json\n{raw}\n```")

    action = data.get("action", "").strip().upper()
    ticker = data.get("signal_ticker", "").strip()

    if not action or not ticker:
        await send_telegram_log("⚠️ Invalid payload: missing 'action' or 'signal_ticker'")
        return {"status": "invalid payload"}

    result = await handle_trading_signal(ticker, action)
    await send_telegram_log(f"🔔 Result: {result}")

    return {"status": "ok", "result": result}
