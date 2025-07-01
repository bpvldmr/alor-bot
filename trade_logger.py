import asyncio
from telegram_logger import send_telegram_log
from auth import get_current_balance
from loguru import logger

async def log_trade_result(ticker: str, side: str, qty: int, entry_price: float, exit_price: float):
    try:
        pnl = round((exit_price - entry_price) * qty, 2)
        pct = round((pnl / (entry_price * abs(qty))) * 100, 2) if entry_price != 0 else 0

    new_balance = await get_current_balance()

        emoji = "🟢" if pnl >= 0 else "🔴"
        action = "LONG" if qty > 0 else "SHORT"

        await send_telegram_log(
            f"{emoji} Сделка завершена:\n"
            f"Тикер: {ticker}\n"
            f"Действие: {action}\n"
            f"Контракты: {abs(qty)}\n"
            f"Вход: {entry_price:.2f} → Выход: {exit_price:.2f}\n"
            f"PnL: {pnl:+.2f} руб. ({pct:+.2f}%)\n"
            f"Баланс: {new_balance:.2f} руб."
        )
    except Exception as e:
        logger.error(f"❌ Ошибка в log_trade_result: {e}")
