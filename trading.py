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

# ─────────────────────────────────── Глобальные состояния ────────────────────
current_positions = {v["trade"]: 0 for v in TICKER_MAP.values()}   # trade = symbol
entry_prices      = {}
last_signals      = {}

initial_balance   = None
last_balance      = None
total_profit      = 0
total_deposit     = 0
total_withdrawal  = 0

SIGNAL_COOLDOWN_SECONDS = 3600      # 1-часовой cooldown для RSI
# ──────────────────────────────────────────────────────────────────────────────

def get_alor_symbol(instrument: str) -> str:
    """Возвращает биржевой symbol для ALOR-API.
       Сейчас trade == symbol, но оставляем гибкость на будущее."""
    for info in TICKER_MAP.values():
        if info["trade"] == instrument:
            return info["symbol"]
    return instrument      # fallback

async def get_account_summary():
    token = await get_access_token()
    url   = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

async def execute_market_order(symbol: str, side: str, qty: int):
    """Отправляет рынок и через 30 с запрашивает фактическую позицию."""
    res = await place_order({
        "side": side.upper(),
        "qty":  qty,
        "instrument": symbol,
        "symbol":     symbol,
    })

    print("📅 Order sent, got response:", res)

    if "error" in res:
        await send_telegram_log(f"❌ {side}/{symbol}/{qty}: {res['error']}")
        return None

    await asyncio.sleep(30)
    snapshot = await get_position_snapshot(symbol)
    actual_position = snapshot.get("qty", 0)

    return {
        "price":     res.get("price", 0.0),
        "order_id":  res.get("order_id", "—"),
        "position":  actual_position
    }

# ════════════════════════  ОСНОВНАЯ ФУНКЦИЯ  ═════════════════════════════════
async def process_signal(tv_tkr: str, sig: str):
    global total_profit, initial_balance, last_balance, total_deposit, total_withdrawal

    await send_telegram_log(f"📅 Обработка сигнала: {tv_tkr} / {sig}")

    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Неизвестный тикер {tv_tkr}")
        return {"error": "Unknown ticker"}

    symbol    = TICKER_MAP[tv_tkr]["trade"]      # trade == symbol
    sig_upper = sig.upper()

    # ─────────────── RSI > 70 / RSI < 30 ─────────────────────────────────────
    if sig_upper in ("RSI>70", "RSI<30"):
        now = time.time()
        key = f"{symbol}:{sig_upper}"
        if last_signals.get(key) and now - last_signals[key] < SIGNAL_COOLDOWN_SECONDS:
            await send_telegram_log(f"⏳ Сигнал проигнорирован (cooldown): {tv_tkr}/{sig}")
            return {"status": "ignored"}
        last_signals[key] = now

        positions = await get_current_positions()
        cur = positions.get(symbol, 0)
        current_positions[symbol] = cur

        if cur == 0:
            await send_telegram_log(f"⚠️ Нет открытой позиции по {symbol}, сигнал {sig} проигнорирован")
            return {"status": "no_position"}

        if sig_upper == "RSI>70":
            if cur > 0:
                half = abs(cur) // 2
                if half:
                    res = await execute_market_order(symbol, "sell", half)
                    if res:
                        current_positions[symbol] = cur - half
                        await send_telegram_log(
                            f"📉 RSI>70: Продаём половину LONG по {symbol}\nКонтракты: {half}\nЦена: {res['price']:.2f}"
                        )
                return {"status": "partial_long_close"}
            await send_telegram_log(f"⚠️ RSI>70: У вас SHORT по {symbol}, ничего не делаем")
            return {"status": "noop"}

        if sig_upper == "RSI<30":
            if cur < 0:
                half = abs(cur) // 2
                if half:
                    res = await execute_market_order(symbol, "buy", half)
                    if res:
                        current_positions[symbol] = cur + half
                        await send_telegram_log(
                            f"📈 RSI<30: Покупаем половину SHORT по {symbol}\nКонтракты: {half}\nЦена: {res['price']:.2f}"
                        )
                return {"status": "partial_short_close"}
            await send_telegram_log(f"⚠️ RSI<30: У вас LONG по {symbol}, ничего не делаем")
            return {"status": "noop"}

    # ─────────────── LONG0 / SHORT0  (полное закрытие) ───────────────────────
    if sig_upper in ("LONG0", "SHORT0"):
        positions = await get_current_positions()
        cur = positions.get(symbol, 0)
        current_positions[symbol] = cur

        if cur == 0:
            await send_telegram_log(f"⚠️ Нет позиции по {symbol}, сигнал {sig_upper} проигнорирован")
            return {"status": "no_position"}

        # LONG0 закрывает SHORT, SHORT0 закрывает LONG
        need_close_short = sig_upper == "LONG0"  and cur < 0
        need_close_long  = sig_upper == "SHORT0" and cur > 0
        if not (need_close_short or need_close_long):
            await send_telegram_log(
                f"⚠️ Сигнал {sig_upper} не совпадает с направлением позиции {cur:+}"
            )
            return {"status": "direction_mismatch"}

        side = "buy" if cur < 0 else "sell"
        qty  = abs(cur)

        res = await execute_market_order(symbol, side, qty)
        if res:
            current_positions[symbol] = 0
            entry_prices.pop(symbol, None)
            await send_telegram_log(
                f"🔒 {sig_upper}: позиция по {symbol} закрыта полностью\n"
                f"Контракты: {qty}\nЦена: {res['price']:.2f}"
            )
            summary = await get_account_summary()
            await send_balance_to_telegram(summary, total_profit, initial_balance or 1)
        return {"status": "close_all"}

    # ─────────────── Обычные LONG / SHORT ────────────────────────────────────
    dir_  = 1 if sig_upper == "LONG" else -1
    side  = "buy" if dir_ > 0 else "sell"

    positions = await get_current_positions()
    cur = positions.get(symbol, 0)
    current_positions[symbol] = cur

    # 1⃣ Переворот ------------------------------------------------------------
    if cur * dir_ < 0:
        await send_telegram_log(f"🔄 Переворот: {symbol}, сигнал {sig_upper}, позиция {cur}")
        total_qty = abs(cur) + START_QTY[symbol]
        res = await execute_market_order(symbol, side, total_qty)
        if res:
            price = res["price"]
            actual_position = res["position"]
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
                ticker=symbol,
                side="LONG" if cur > 0 else "SHORT",
                qty=cur,
                entry_price=prev_entry,
                exit_price=price
            )

            if actual_position * dir_ > 0:   # переворот удался
                current_positions[symbol] = actual_position
                entry_prices[symbol]      = price
                emoji = "🔻" if pnl < 0 else "🟢"
                await send_telegram_log(
                    f"{emoji} Переворот завершён:\n"
                    f"Тикер: {symbol}\n"
                    f"Действие: {'LONG' if cur > 0 else 'SHORT'} → "
                    f"{'LONG' if dir_ > 0 else 'SHORT'}\n"
                    f"Контракты: {abs(total_qty)}\n"
                    f"Вход: {prev_entry:.2f} → Выход: {price:.2f}\n"
                    f"PnL: {pnl:+.2f} руб. ({pct:+.2f}%)\n"
                    f"Баланс: {current_balance:.2f} руб."
                )
            else:
                await send_telegram_log(
                    f"⚠️ Переворот не завершён! Запрошено {total_qty}, позиция: {actual_position:+}"
                )

            summary = await get_account_summary()
            await send_balance_to_telegram(summary, total_profit, initial_balance or 1)

        return {"status": "flip"}

    # 2⃣ Усреднение -----------------------------------------------------------
    if cur * dir_ > 0:
        new = cur + ADD_QTY[symbol]
        if abs(new) > MAX_QTY[symbol]:
            await send_telegram_log(f"❌ Превышен лимит по {symbol}: {MAX_QTY[symbol]}")
            return {"status": "limit"}

        res = await execute_market_order(symbol, side, ADD_QTY[symbol])
        if res:
            price = res["price"]
            entry_prices[symbol] = (
                (entry_prices.get(symbol, 0) * abs(cur) + price * ADD_QTY[symbol]) / abs(new)
            )
            current_positions[symbol] = new
            await send_telegram_log(
                f"➕ Усреднение {symbol}={new:+} @ {entry_prices[symbol]:.2f}"
            )

            summary = await get_account_summary()
            await send_balance_to_telegram(summary, total_profit, initial_balance or 1)

        return {"status": "avg"}

    # 3⃣ Открытие -------------------------------------------------------------
    if cur == 0:
        res = await execute_market_order(symbol, side, START_QTY[symbol])
        if res:
            price = res["price"]
            current_positions[symbol] = dir_ * START_QTY[symbol]
            entry_prices[symbol]      = price
            await send_telegram_log(
                f"✅ Открыта {symbol}={dir_ * START_QTY[symbol]:+} @ {price:.2f}"
            )

            summary = await get_account_summary()
            await send_balance_to_telegram(summary, total_profit, initial_balance or 1)

        return {"status": "open"}

    return {"status": "noop"}

# ──────────────────────────────────────────────────────────────────────────────
__all__ = ["total_profit", "initial_balance"]
