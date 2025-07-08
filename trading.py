# trading.py — полная версия
# Логика: RSI-cooldown 2 ч, первое срабатывание закрывает ½, второе — остаток
# если за это время не было переворота; после flip счётчики RSI обнуляются.

import asyncio
import time
import httpx
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
current_positions = {v["trade"]: 0 for v in TICKER_MAP.values()}   # trade == symbol
entry_prices: dict[str, float] = {}

# для RSI-контроля
last_signals: dict[str, float] = {}          # key → timestamp
rsi_state:   dict[str, dict]   = {}          # key → {"count":1, "dir":±1}

initial_balance = last_balance = None
total_profit = total_deposit = total_withdrawal = 0

SIGNAL_COOLDOWN_SECONDS = 7200    # 2-часовой cool-down для RSI
# ─────────────────────────────────────────────────────────────────────────────


def get_alor_symbol(instrument: str) -> str:
    """Сейчас trade == symbol, но оставляем гибкость."""
    for info in TICKER_MAP.values():
        if info["trade"] == instrument:
            return info["symbol"]
    return instrument


async def get_account_summary():
    token = await get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, headers=headers)
        r.raise_for_status()
        return r.json()


async def execute_market_order(symbol: str, side: str, qty: int):
    """Маркет-ордер + 30 с ожидание фактического qty."""
    res = await place_order({
        "side": side.upper(),
        "qty":  qty,
        "instrument": symbol,
        "symbol":     symbol,
    })
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

    symbol    = TICKER_MAP[tv_tkr]["trade"]       # "CNY-9.25" / "NG-7.25"
    sig_upper = sig.upper()

    # ────────────────────── RSI блок ─────────────────────────────────────────
    if sig_upper in ("RSI>70", "RSI<30"):
        now, key = time.time(), f"{symbol}:{sig_upper}"

        # ► cool-down 2 ч
        if key in last_signals and now - last_signals[key] < SIGNAL_COOLDOWN_SECONDS:
            await send_telegram_log("⏳ RSI-сигнал проигнорирован (cool-down 2 ч)")
            return {"status": "ignored"}
        last_signals[key] = now

        positions = await get_current_positions()
        cur = positions.get(symbol, 0)
        current_positions[symbol] = cur
        if cur == 0:
            await send_telegram_log(f"⚠️ Нет позиции по {symbol} – RSI игнорируется")
            return {"status": "no_position"}

        want_sell = sig_upper == "RSI>70" and cur > 0
        want_buy  = sig_upper == "RSI<30" and cur < 0
        if not (want_sell or want_buy):
            await send_telegram_log("⚠️ RSI направление ≠ позиции – пропуск")
            return {"status": "noop"}

        side = "sell" if want_sell else "buy"
        state = rsi_state.get(key, {"count": 0, "dir": 0})
        same_dir = state["dir"] == (1 if cur > 0 else -1)

        # первое срабатывание
        if state["count"] == 0 or not same_dir:
            qty_close = max(abs(cur) // 2, 1)
            rsi_state[key] = {"count": 1, "dir": 1 if cur > 0 else -1}
            note = "половину"
        # второе срабатывание без переворота
        else:
            qty_close = abs(cur)
            rsi_state.pop(key, None)
            note = "всю оставшуюся"

        res = await execute_market_order(symbol, side, qty_close)
        if res:
            current_positions[symbol] = cur - qty_close if side == "sell" else cur + qty_close
            await send_telegram_log(
                f"🔔 {sig_upper}: {note} позиции по {symbol}\n"
                f"Контракты: {qty_close}\nЦена: {res['price']:.2f}"
            )
        return {"status": "rsi_close"}

    # ────────────────────── LONG / SHORT ─────────────────────────────────────
    if sig_upper not in ("LONG", "SHORT"):
        await send_telegram_log(f"⚠️ Неизвестный сигнал {sig_upper}")
        return {"status": "invalid_action"}

    dir_  = 1 if sig_upper == "LONG" else -1
    side  = "buy" if dir_ > 0 else "sell"
    positions = await get_current_positions()
    cur = positions.get(symbol, 0)
    current_positions[symbol] = cur

    # 1️⃣ Переворот
    if cur * dir_ < 0:
        total_qty = abs(cur) + START_QTY[symbol]
        res = await execute_market_order(symbol, side, total_qty)
        if res:
            price = res["price"]
            actual_position = res["position"]

            # сброс всей RSI-истории
            for k in list(rsi_state):
                if k.startswith(symbol + ":"):
                    rsi_state.pop(k, None)
            for k in list(last_signals):
                if k.startswith(symbol + ":"):
                    last_signals.pop(k, None)

            prev_entry = entry_prices.get(symbol, 0)
            pnl = (price - prev_entry) * cur
            pct = (pnl / (abs(prev_entry) * abs(cur)) * 100) if prev_entry else 0

            current_balance = await get_current_balance()
            if initial_balance is None:
                initial_balance = current_balance
                last_balance    = current_balance

            theoretical_balance = last_balance + pnl
            diff = round(current_balance - theoretical_balance, 2)
            if diff > 10:
                total_deposit += diff
            elif diff < -10:
                total_withdrawal += abs(diff)

            last_balance = current_balance
            total_profit += pnl

            await log_trade_result(
                ticker=symbol, side="LONG" if cur > 0 else "SHORT",
                qty=cur, entry_price=prev_entry, exit_price=price
            )

            if actual_position * dir_ > 0:
                current_positions[symbol] = actual_position
                entry_prices[symbol] = price
                await send_telegram_log(
                    f"🟢 Переворот {symbol} завершён, новая позиция {actual_position:+}"
                )
        return {"status": "flip"}

    # 2️⃣ Усреднение
    if cur * dir_ > 0:
        new = cur + ADD_QTY[symbol]
        if abs(new) > MAX_QTY[symbol]:
            await send_telegram_log(f"❌ Лимит по {symbol}: {MAX_QTY[symbol]}")
            return {"status": "limit"}

        res = await execute_market_order(symbol, side, ADD_QTY[symbol])
        if res:
            price = res["price"]
            entry_prices[symbol] = (
                (entry_prices.get(symbol, 0) * abs(cur) + price * ADD_QTY[symbol]) / abs(new)
            )
            current_positions[symbol] = new
            await send_telegram_log(f"➕ Усреднение {symbol}={new:+} @ {entry_prices[symbol]:.2f}")
        return {"status": "avg"}

    # 3️⃣ Открытие
    if cur == 0:
        res = await execute_market_order(symbol, side, START_QTY[symbol])
        if res:
            price = res["price"]
            current_positions[symbol] = dir_ * START_QTY[symbol]
            entry_prices[symbol] = price
            await send_telegram_log(
                f"✅ Открыта {symbol}={dir_ * START_QTY[symbol]:+} @ {price:.2f}"
            )
        return {"status": "open"}

    return {"status": "noop"}


__all__ = ["total_profit", "initial_balance"]
