# trading.py
# Логика по сигналам:
# • RSI>80 / RSI<20  – если позиция 0, открывает половину старт-объёма (SHORT или LONG)
# • RSI>70 / RSI<30  – 2-часовой cool-down; 1-й сигнал закрывает ½ позиции,
#   2-й (если не было flip) закрывает остаток
# • После удачного flip счётчики RSI и таймеры обнуляются

import asyncio, time, httpx
from telegram_logger import send_telegram_log
from config import (
    TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY,
    BASE_URL, ACCOUNT_ID
)
from auth   import get_current_balance, get_access_token
from alor   import place_order, get_position_snapshot, get_current_positions
from trade_logger import log_trade_result
from balance      import send_balance_to_telegram

# ────────────────────────── Глобальные переменные ───────────────────────────
current_positions = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices: dict[str, float] = {}

last_signals: dict[str, float] = {}          # key (sym:rsiX) → timestamp
rsi_state:   dict[str, dict]   = {}          # для 70/30: key → {"count":1, "dir":±1}

initial_balance = last_balance = None
total_profit = total_deposit = total_withdrawal = 0

SIGNAL_COOLDOWN_SECONDS = 7200    # 2-часовой cool-down для всех RSI
# ─────────────────────────────────────────────────────────────────────────────


async def execute_market_order(symbol: str, side: str, qty: int):
    """Маркет-ордер и подтверждение позиции через 30 с"""
    res = await place_order({"side": side.upper(), "qty": qty,
                             "instrument": symbol, "symbol": symbol})
    if "error" in res:
        await send_telegram_log(f"❌ {side}/{symbol}/{qty}: {res['error']}")
        return None
    await asyncio.sleep(30)
    snap = await get_position_snapshot(symbol)
    return {"price": res.get("price", 0.0), "position": snap.get("qty", 0)}


# ═════════════════════  ОБРАБОТКА СИГНАЛА  ═══════════════════════════════════
async def process_signal(tv_tkr: str, sig: str):
    global total_profit, initial_balance, last_balance, total_deposit, total_withdrawal

    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Неизвестный тикер {tv_tkr}")
        return {"error": "Unknown ticker"}

    symbol    = TICKER_MAP[tv_tkr]["trade"]     # "CNY-9.25" / "NG-7.25"
    sig_upper = sig.upper()

    # ───────── NEW: RSI>80  /  RSI<20  (открытие половины старт-объёма) ──────
    if sig_upper in ("RSI>80", "RSI<20"):
        now, key = time.time(), f"{symbol}:{sig_upper}"
        if key in last_signals and now - last_signals[key] < SIGNAL_COOLDOWN_SECONDS:
            await send_telegram_log("⏳ RSI80/20 проигнорирован (cool-down 2 ч)")
            return {"status": "ignored"}
        last_signals[key] = now

        positions = await get_current_positions()
        cur = positions.get(symbol, 0)
        if cur != 0:
            await send_telegram_log("⚠️ RSI80/20: позиция не нулевая – сигн."
                                     " игнорируется"); return {"status": "non_zero_pos"}

        half_qty = max(START_QTY[symbol] // 2, 1)
        if sig_upper == "RSI>80":
            side, dir_sign = "sell", -1
            descr = "SHORT"
        else:
            side, dir_sign = "buy", 1
            descr = "LONG"

        res = await execute_market_order(symbol, side, half_qty)
        if res:
            current_positions[symbol] = dir_sign * half_qty
            entry_prices[symbol]      = res["price"]
            await send_telegram_log(
                f"🚀 {sig_upper}: открыт {descr} {half_qty} по {symbol} @ {res['price']:.2f}"
            )
        return {"status": "rsi80_20_open"}

    # ───────── EXISTING: RSI>70  /  RSI<30  (частичное / полное закрытие) ────
    if sig_upper in ("RSI>70", "RSI<30"):
        now, key = time.time(), f"{symbol}:{sig_upper}"
        if key in last_signals and now - last_signals[key] < SIGNAL_COOLDOWN_SECONDS:
            await send_telegram_log("⏳ RSI70/30 проигнорирован (cool-down 2 ч)")
            return {"status": "ignored"}
        last_signals[key] = now

        positions = await get_current_positions()
        cur = positions.get(symbol, 0)
        if cur == 0:
            await send_telegram_log("⚠️ Нет позиции – RSI70/30 игнорируется")
            return {"status": "no_position"}

        want_sell = sig_upper == "RSI>70" and cur > 0
        want_buy  = sig_upper == "RSI<30" and cur < 0
        if not (want_sell or want_buy):
            await send_telegram_log("⚠️ RSI70/30 направление ≠ позиции – пропуск")
            return {"status": "noop"}

        side = "sell" if want_sell else "buy"
        state = rsi_state.get(key, {"count": 0, "dir": 0})
        same_dir = state["dir"] == (1 if cur > 0 else -1)

        if state["count"] == 0 or not same_dir:          # первый раз
            qty_close = max(abs(cur)//2, 1)
            rsi_state[key] = {"count": 1, "dir": 1 if cur > 0 else -1}
            part = "половину"
        else:                                            # второй раз
            qty_close = abs(cur)
            rsi_state.pop(key, None)
            part = "остаток"

        res = await execute_market_order(symbol, side, qty_close)
        if res:
            await send_telegram_log(
                f"🔔 {sig_upper}: закрываем {part} по {symbol} "
                f"({qty_close} @ {res['price']:.2f})"
            )
        return {"status": "rsi70_30_close"}

    # ───────── LONG / SHORT (переворот, усреднение, открытие) ────────────────
    if sig_upper not in ("LONG", "SHORT"):
        await send_telegram_log(f"⚠️ Неизвестный сигнал {sig_upper}")
        return {"status": "invalid_action"}

    dir_  = 1 if sig_upper == "LONG" else -1
    side  = "buy" if dir_ > 0 else "sell"
    positions = await get_current_positions()
    cur = positions.get(symbol, 0)

    # 1⃣ Переворот
    if cur * dir_ < 0:
        total_qty = abs(cur) + START_QTY[symbol]
        res = await execute_market_order(symbol, side, total_qty)
        if res:
            # обнулить все RSI-счётчики/таймеры
            for k in list(rsi_state):
                if k.startswith(symbol + ":"): rsi_state.pop(k, None)
            for k in list(last_signals):
                if k.startswith(symbol + ":"): last_signals.pop(k, None)
            await send_telegram_log(f"🟢 Flip {symbol}: позиция перевёрнута")
        return {"status": "flip"}

    # 2⃣ Усреднение
    if cur * dir_ > 0:
        new = cur + ADD_QTY[symbol]
        if abs(new) > MAX_QTY[symbol]:
            await send_telegram_log(f"❌ Лимит по {symbol}: {MAX_QTY[symbol]}")
            return {"status": "limit"}
        res = await execute_market_order(symbol, side, ADD_QTY[symbol])
        if res:
            await send_telegram_log(
                f"➕ Усреднение {symbol}: новая позиция {new:+} @ {res['price']:.2f}"
            )
        return {"status": "avg"}

    # 3⃣ Открытие
    if cur == 0:
        res = await execute_market_order(symbol, side, START_QTY[symbol])
        if res:
            await send_telegram_log(
                f"✅ Открыта {symbol}={dir_ * START_QTY[symbol]:+} @ {res['price']:.2f}"
            )
        return {"status": "open"}

    return {"status": "noop"}


__all__ = ["total_profit", "initial_balance"]
