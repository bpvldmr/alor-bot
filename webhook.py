from fastapi import APIRouter, Request
import json
from telegram_logger import send_telegram_log
from trading import handle_trading_signal

router = APIRouter()
SECRET = "sEcr09!@"

@router.post("/webhook/{token}")
async def webhook(token:str, request: Request):
    # Маршрут: /webhook/sEcr09!@ 
    if token != SECRET:
        return {"status":"unauthorized"}

    raw = (await request.body()).decode()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        send_telegram_log(f"❌ JSON decode error: {e}\n{raw}")
        return {"status":"invalid json"}

    send_telegram_log(f"📩 TV → Bot:\n```json\n{raw}\n```")
    sig = data.get("action")
    tkr = data.get("signal_ticker")
    if not sig or not tkr:
        return {"status":"invalid payload"}

    res = await handle_trading_signal(tkr, sig.upper())
    send_telegram_log(f"🔔 Result: {res}")
    return {"status":"ok", "result":res}
