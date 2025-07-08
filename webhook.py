# webhook.py — принимает сигналы от TradingView и передаёт их в trading.process_signal

from fastapi import APIRouter, Request
import json
from telegram_logger import send_telegram_log
from trading import process_signal
from auth import get_current_balance

router = APIRouter()

# ─────────────────── защита токеном ──────────────────────────────────────────
SECRET_TOKEN = "sEcr0901A2B3"

# допустимые действия из TradingView
VALID_ACTIONS = {
    "LONG", "SHORT",
    "RSI>70", "RSI<30",
    "RSI>80", "RSI<20"          # ← новые уровни
}

# ───────────────────────── маршрутизатор ─────────────────────────────────────
@router.post("/webhook/{token}")
async def webhook(token: str, request: Request):
    token = token.strip()

    if token != SECRET_TOKEN:
        await send_telegram_log(f"❌ Неверный токен в URL: `{token}`")
        return {"status": "unauthorized"}

    # ─── читаем и парсим тело ───────────────────────────────────────────────
    try:
        raw_body = await request.body()
        if not raw_body:
            await send_telegram_log("⚠️ Пустое тело запроса")
            return {"status": "empty body"}

        raw  = raw_body.decode("utf-8").strip()
        data = json.loads(raw)

    except json.JSONDecodeError as e:
        await send_telegram_log(f"❌ JSON decode error: {e}\nRaw: {raw}")
        return {"status": "invalid json"}

    except Exception as e:
        await send_telegram_log(f"❌ Ошибка при разборе тела запроса: {e}")
        return {"status": "error", "message": str(e)}

    await send_telegram_log(f"📩 Получен сигнал:\n```json\n{raw}\n```")

    # ─── извлекаем поля ─────────────────────────────────────────────────────
    action = data.get("action", "").strip().upper()
    ticker = data.get("signal_ticker", "").strip()

    if not action or not ticker:
        await send_telegram_log("⚠️ Ошибка: отсутствует 'action' или 'signal_ticker'")
        return {"status": "invalid payload"}

    if action not in VALID_ACTIONS:
        await send_telegram_log(f"⚠️ Неизвестный тип сигнала: `{action}`")
        return {"status": "invalid action"}

    # ─── передаём в core-логику ─────────────────────────────────────────────
    try:
        result = await process_signal(ticker, action)
        await send_telegram_log(f"✅ Обработка завершена:\n{result}")
        return {"status": "ok", "result": result}

    except Exception as e:
        try:
            balance = await get_current_balance()
            await send_telegram_log(
                f"❌ Ошибка при обработке сигнала: {e}\n"
                f"📊 Текущий баланс: {balance:.2f} ₽"
            )
        except Exception as be:
            await send_telegram_log(
                f"❌ Ошибка при обработке сигнала: {e}\n"
                f"⚠️ Также ошибка при получении баланса: {be}"
            )
        return {"status": "error", "message": str(e)}
