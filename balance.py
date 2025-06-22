# balance.py

from fastapi import APIRouter
from config import get_current_balance
from telegram_logger import send_telegram_log

balance_router = APIRouter()

@balance_router.get("/test-balance")
async def test_balance():
    balance = get_current_balance()
    send_telegram_log(f"🧾 Текущий баланс: {balance:.2f}₽")
    return {"balance": balance}
