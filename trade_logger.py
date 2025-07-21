# trade_logger.py
# ────────────────────────────────────────────────────────────────
# 2025‑07‑21  patch‑4
#
# ✓ Используем calc_pnl() из pnl_calc.py — единый центр расчёта.
# ✓ Ловим price == 0.0 и пишем warning в лог.
# ✓ Добавили asyncio‑Lock, чтобы избежать гонок при параллельных вызовах.
# ✓ Логика сообщений и агрегирования PnL сохранена.
# ────────────────────────────────────────────────────────────────
import asyncio
from collections import defaultdict
from datetime import datetime

from telegram_logger import send_telegram_log
from loguru          import logger
from pnl_calc        import calc_pnl           # ← централизованный расчёт PnL

# ────────── shared‑state + защита от гонок ──────────────────────────────────
lock = asyncio.Lock()   # один на весь модуль

pnl_history: list[tuple[datetime, float]] = []           # (closed_at, pnl)
instrument_pnl:   defaultdict[str, float] = defaultdict(float)
instrument_price: dict[str, dict[str, float]] = {}       # {'entry': .., 'exit': ..}
open_positions:   dict[str, tuple[int, float]] = {}      # ticker → (qty, entry_price)


async def register_trade(
    ticker: str,
    action: str,      # "buy"/"sell"  (или "long"/"short")
    qty: int,
    price: float
) -> None:
    """
    Регистрирует ЛЮБУЮ исполненную заявку.
    Когда позиция = 0  →  фиксируем PnL и шлём отчёт.
    """
    if price == 0.0:
        logger.warning(f"[{ticker}] Price is 0.0 — проверь /trades!")
    action_lc   = action.lower()
    side_coeff  = 1 if action_lc in ("buy", "long") else -1
    qty_signed  = qty * side_coeff

    async with lock:
        pos_qty, pos_entry = open_positions.get(ticker, (0, 0.0))
        new_qty            = pos_qty + qty_signed

        # 1️⃣ Открытие позиции
        if pos_qty == 0 and new_qty != 0:
            open_positions[ticker] = (new_qty, price)
            logger.debug(f"[{ticker}] opened {new_qty:+} @ {price}")
            return

        # 2️⃣ Частичное закрытие / докупка
        if new_qty != 0:
            # усреднение в ту же сторону
            if (new_qty > 0 and pos_qty > 0) or (new_qty < 0 and pos_qty < 0):
                total_cost = pos_entry * abs(pos_qty) + price * abs(qty_signed)
                open_positions[ticker] = (new_qty, total_cost / abs(new_qty))
            else:
                # частичное закрытие — entry остаётся прежним
                open_positions[ticker] = (new_qty, pos_entry)
            logger.debug(f"[{ticker}] adjusted to {new_qty:+} @ {open_positions[ticker][1]:.2f}")
            return

        # 3️⃣ Полное закрытие
        await _finalize_closed_trade(
            ticker,
            closed_qty=qty_signed,      # знак важен
            entry_price=pos_entry,
            exit_price=price
        )
        open_positions.pop(ticker, None)


async def _finalize_closed_trade(
    ticker: str,
    closed_qty: int,
    entry_price: float,
    exit_price: float
):
    """Считаем PnL (через calc_pnl) и отправляем сообщения."""
    pnl, pct = calc_pnl(entry_price, exit_price, closed_qty)
    pnl_history.append((datetime.now(), pnl))

    instrument_pnl[ticker]   += pnl
    instrument_price[ticker]  = {"entry": entry_price, "exit": exit_price}

    emoji = "🟢" if pnl >= 0 else "🔴"

    await send_telegram_log(
        f"{emoji} Сделка завершена:\n"
        f"Тикер: {ticker}\n"
        f"Действие: {'LONG' if closed_qty < 0 else 'SHORT'}\n"
        f"Контракты: {abs(closed_qty)}\n"
        f"Вход: {entry_price:.2f} → Выход: {exit_price:.2f}\n"
        f"PnL: {pnl:+.2f} руб. ({pct:+.2f}%)"
    )

    await send_telegram_log(_build_instrument_report())


def _build_instrument_report() -> str:
    if not instrument_pnl:
        return "📊 Пока нет закрытых сделок."
    lines = [
        f"{tkr}: {total:+.2f} ₽ "
        f"(посл. {instrument_price[tkr]['entry']:.2f} → {instrument_price[tkr]['exit']:.2f})"
        for tkr, total in instrument_pnl.items()
    ]
    return "📊 PnL по инструментам:\n" + "\n".join(lines)
# ────────────────────────────────────────────────────────────────
