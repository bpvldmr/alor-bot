# webhook.py

import json
from fastapi import APIRouter, Request
from telegram_logger import send_telegram_log
from trading import handle_signal   # синхронная функция

webhook_router = APIRouter()
SECRET_TOKEN = "sEcr09!@"

@webhook_router.post("/webhook/9f3c7e23da9f49bd84f243acbc2af21a")
async def webhook(request: Request):
    # 1. Читаем сырой body
    raw = await request.body()
    text = raw.decode("utf-8")

    # 2. Парсим JSON вручную
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        send_telegram_log(f"❌ Ошибка парсинга JSON: {e}\n{text}")
        return {"status": "invalid json"}

    # 3. Логируем полный payload
    send_telegram_log(f"📩 Получен сигнал от TradingView:\n```json\n{text}\n```")

    # 4. Проверяем токен
    if data.get("token") != SECRET_TOKEN:
        send_telegram_log("❌ Неверный токен в сигнале TradingView")
        return {"status": "unauthorized"}

    # 5. Берём обязательные поля
    signal_ticker = data.get("signal_ticker")
    action = data.get("action")
    if not signal_ticker or not action:
        send_telegram_log("⚠️ Ошибка: signal_ticker или action отсутствует")
        return {"status": "invalid payload"}

    # 6. Вызываем обработчик сигналов (синхронную функцию!)
    result = handle_signal(signal_ticker, action.upper())  # LONG или SHORT

    # 7. Логируем и возвращаем результат
    send_telegram_log(f"✅ Обработан сигнал: {signal_ticker} → {action.upper()}\nРезультат: {result}")
    return {"status": "ok", "result": result}
