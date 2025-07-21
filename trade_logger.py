# trade_logger.py
# ────────────────────────────────────────────────────────────────
# 2025‑07‑21  patch‑3
#
# • register_trade теперь принимает action = "buy" / "sell"
#   (совместимо с "long" / "short").
# • Логика PnL и отчётов не изменилась.
# ────────────────────────────────────────────────────────────────

from collections import defaultdict
from datetime import datetime

from telegram_logger import send_telegram_log
from loguru          import logger

pnl_history: list[tuple[datetime, float]] = []           # (closed_at, pnl)
instrument_pnl:   defaultdict[str, float] = defaultdict(float)
instrument_price: dict[str, dict[str, float]] = {}       # {'entry': .., 'exit': ..}
open_positions:   dict[str, tuple[int, float]] = {}      # ticker → (qty, entry_price)


async def register_trade(
    ticker: str,
    action: str,          # "buy"/"sell"  (или "long"/"short" для совместимости)
    qty: int,
    price: float
) -> None:
    """
    Регистрирует ЛЮБУЮ исполненную заявку. Когда позиция по тикеру
    возвращается к нулю → фиксируется итоговый PnL и шлётся отчёт.
    """
    action_lc   = action.lower()
    side_coeff  = 1 if action_lc in ("buy", "long") else -1
    qty_signed  = qty * side_coeff

    pos_qty, pos_entry = open_positions.get(ticker, (0, 0.0))
    new_qty            = pos_qty + qty_signed

    # 1. Открытие новой позиции
    if pos_qty == 0 and new_qty != 0:
        open_positions[ticker] = (new_qty, price)
        logger.debug(f"[{ticker}] opened {new_qty:+} @ {price}")
        return

    # 2. Частичное закрытие / докупка
    if new_qty != 0:
        if (new_qty > 0 and pos_qty > 0) or (new_qty < 0 and pos_qty < 0):
            total_cost = pos_entry * abs(pos_qty) + price * abs(qty_signed)
            open_positions[ticker] = (new_qty, total_cost / abs(new_qty))
        else:
            open_positions[ticker] = (new_qty, pos_entry)
        logger.debug(f"[{ticker}] adjusted to {new_qty:+} @ {open_positions[ticker][1]:.2f}")
        return

    # 3. Полное закрытие позиции
    await _finalize_closed_trade(
        ticker,
        closed_qty=qty_signed,    # знак важен
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
    """Считаем итоговый PnL и отправляем два сообщения."""
    pnl = round((exit_price - entry_price) * closed_qty * -1, 2)
    pct = round((pnl / (entry_price * abs(closed_qty))) * 100, 2) if entry_price else 0.0
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
