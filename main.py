from fastapi import FastAPI, APIRouter, Request
from loguru import logger
from trading import handle_trading_signal  # ✅ прямой импорт сигнальной функции

app = FastAPI()
webhook_router = APIRouter()

# 🔐 Токен защиты вебхука
VALID_TOKEN = "sEcr0901A2B3"

@webhook_router.post("/webhook/{token}")
async def webhook(request: Request, token: str):
    if token != VALID_TOKEN:
        logger.warning(f"❌ Неверный токен в URL: {token}")
        return {"error": f"❌ Неверный токен в URL: {token}"}

    try:
        data = await request.json()
        signal_ticker = data.get("signal_ticker")
        action = data.get("action")

        if not signal_ticker or not action:
            return {"error": "Нужно передать signal_ticker и action"}

        result = await handle_trading_signal(signal_ticker, action)  # ✅ вызываем напрямую
        logger.info(f"✅ Сигнал обработан: {signal_ticker}, действие: {action} → {result}")
        return result

    except Exception as e:
        logger.error(f"❌ Ошибка обработки сигнала: {e}")
        return {"error": str(e)}

# ✅ Регистрируем маршруты
app.include_router(webhook_router)

# 🔄 Тестовый эндпоинт
@app.get("/")
async def root():
    return {"status": "ok", "message": "🚀 Бот запущен"}
