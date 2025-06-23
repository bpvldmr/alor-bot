from fastapi import APIRouter
from config import get_current_balance  # ✅ Исправлено: берём из config
from telegram_logger import send_telegram_log

balance_router = APIRouter()

@balance_router.get("/test-balance")
async def test_balance():
    try:
        balance = get_current_balance()
        send_telegram_log(f"🧾 Текущий баланс: {balance:.2f}₽")
        return {"balance": balance}
    except Exception as e:
        error_msg = f"❌ Ошибка получения баланса в endpoint: {e}"
        send_telegram_log(error_msg)
        return {"error": str(e)}
