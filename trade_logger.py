# trade_logger.py
# ────────────────────────────────────────────────────────────────
import asyncio
from collections import defaultdict
from datetime import datetime

from telegram_logger import send_telegram_log
from loguru          import logger

# Журнал всех закрытых сделок
pnl_history: list[tuple[datetime, float]] = []           # (time_closed, pnl)

# Учёт по каждому инструменту
instrument_pnl:   defaultdict[str, float]          = defaultdict(float)  # совокупный PnL
instrument_price: dict[str, dict[str, float]]      = {}                  # {'entry': .., 'exit': ..}

# Открытые позиции  (ticker → (qty, entry_price))
open_positions: dict[str, tuple[int, float]] = {}       # позитивный qty для LONG, отрицательный для SHORT


async def register_trade(
    ticker: str,
    action: str,                # "LONG" | "SHORT"
    qty: int,
    price: float
) -> None:
    """
    Регистрирует любое исполнение (открытие, докупка, частичное закрытие, реверс).
    • Когда позиция становится 0 → считается итоговый PnL и шлётся отчёт.
    """
    side_coeff = 1 if action.upper() == "LONG" else -1
    qty_signed = qty * side_coeff                    # LONG → +qty, SHORT → -qty

    pos_qty, pos_entry = open_positions.get(ticker, (0, 0.0))
    new_qty = pos_qty + qty_signed

    # 1️⃣ ПОЗИЦИЯ ОТКРЫВАЕТСЯ
    if pos_qty == 0 and new_qty != 0:
        open_positions[ticker] = (new_qty, price)
        logger.debug(f"[{ticker}] opened {new_qty:+} @ {price}")
        return

    # 2️⃣ ДОКУПКА / ЧАСТИЧНОЕ ЗАКРЫТИЕ
    if new_qty != 0:
        # пересчитываем среднюю цену, если направление то же
        if (new_qty > 0 and pos_qty > 0) or (new_qty < 0 and pos_qty < 0):
            total_cost = pos_entry * abs(pos_qty) + price * abs(qty_signed)
            open_positions[ticker] = (new_qty, total_cost / abs(new_qty))
        else:
            # частичное закрытие – оставляем прежнюю entry
            open_positions[ticker] = (new_qty, pos_entry)
        logger.debug(f"[{ticker}] adjusted to {new_qty:+} @ {open_positions[ticker][1]:.2f}")
        return

    # 3️⃣ ПОЗИЦИЯ ПОЛНОСТЬЮ ЗАКРЫТА  → считаем PnL
    if new_qty == 0:
        await _finalize_closed_trade(
            ticker,
            closed_qty=qty_signed,         # сколько закрывали (знак важен)
            entry_price=pos_entry,
            exit_price=price
        )
        open_positions.pop(ticker, None)   # позиция закрыта


async def _finalize_closed_trade(
    ticker: str,
    closed_qty: int,
    entry_price: float,
    exit_price: float
) -> None:
    """
    Считает PnL за полный цикл (открытие‑закрытие) и шлёт сообщения.
    """
    # --- PnL ----
    pnl = round((exit_price - entry_price) * closed_qty * -1, 2)  # знак отражает прибыль
    pct = round((pnl / (entry_price * abs(closed_qty))) * 100, 2) if entry_price else 0.0
    pnl_history.append((datetime.now(), pnl))

    # --- учёт по инструменту ---
    instrument_pnl[ticker]   += pnl
    instrument_price[ticker]  = {"entry": entry_price, "exit": exit_price}

    emoji = "🟢" if pnl >= 0 else "🔴"

    # --- сообщение о сделке ---
    await send_telegram_log(
        f"{emoji} Сделка завершена:\n"
        f"Тикер: {ticker}\n"
        f"Действие: {'LONG' if closed_qty < 0 else 'SHORT'}\n"
        f"Контракты: {abs(closed_qty)}\n"
        f"Вход: {entry_price:.2f} → Выход: {exit_price:.2f}\n"
        f"PnL: {pnl:+.2f} руб. ({pct:+.2f}%)"
    )

    # --- сводка по инструментам ---
    await send_telegram_log(_build_instrument_report())


def _build_instrument_report() -> str:
    """
    Совокупный PnL + последняя пара цен по каждому тикеру.
    """
    if not instrument_pnl:
        return "📊 Пока нет закрытых сделок."

    lines: list[str] = []
    for tkr, total in instrument_pnl.items():
        prices = instrument_price.get(tkr, {})
        entry = prices.get("entry", 0.0)
        exit_ = prices.get("exit", 0.0)
        lines.append(
            f"{tkr}: {total:+.2f} ₽ "
            f"(посл. {entry:.2f} → {exit_:.2f})"
        )
    return "📊 PnL по инструментам:\n" + "\n".join(lines)
# ────────────────────────────────────────────────────────────────
