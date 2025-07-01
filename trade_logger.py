import asyncio
from telegram_logger import send_telegram_log
from auth import get_current_balance
from loguru import logger
from datetime import datetime, timedelta

# Журнал всех сделок для расчёта статистики
pnl_history = []  # каждый элемент: (datetime, pnl)

async def log_trade_result(ticker: str, side: str, qty: int, entry_price: float, exit_price: float):
    try:
        now = datetime.now()
        pnl = round((exit_price - entry_price) * qty, 2)
        pct = round((pnl / (entry_price * abs(qty))) * 100, 2) if entry_price != 0 else 0

        new_balance = await get_current_balance()

        emoji = "🟢" if pnl >= 0 else "🔴"
        action = "LONG" if qty > 0 else "SHORT"

        pnl_history.append((now, pnl))

        await send_telegram_log(
            f"{emoji} Сделка завершена:\n"
            f"Тикер: {ticker}\n"
            f"Действие: {action}\n"
            f"Контракты: {abs(qty)}\n"
            f"Вход: {entry_price:.2f} → Выход: {exit_price:.2f}\n"
            f"PnL: {pnl:+.2f} руб. ({pct:+.2f}%)\n"
            f"Баланс: {new_balance:.2f} руб."
        )

        await send_performance_summary()

    except Exception as e:
        logger.error(f"❌ Ошибка в log_trade_result: {e}")


async def send_performance_summary():
    if not pnl_history:
        return

    now = datetime.now()
    day_ago = now - timedelta(days=1)
    month_ago = now - timedelta(days=30)
    year_ago = now - timedelta(days=365)

    day_pnl = sum(p for d, p in pnl_history if d >= day_ago)
    month_pnl = sum(p for d, p in pnl_history if d >= month_ago)
    year_pnl = sum(p for d, p in pnl_history if d >= year_ago)
    total_pnl = sum(p for _, p in pnl_history)

    summary_text = (
        "📊 Доходность по сделкам:\n"
        f"• За день: {day_pnl:+.2f} ₽\n"
        f"• За месяц: {month_pnl:+.2f} ₽\n"
        f"• За год: {year_pnl:+.2f} ₽\n"
        f"• Всего: {total_pnl:+.2f} ₽"
    )

    await send_telegram_log(summary_text)
