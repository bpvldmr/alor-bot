import asyncio
import time
from telegram_logger import send_telegram_log
from config import TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY
from auth import get_current_balance
from alor import place_order, get_position_snapshot
from trade_logger import log_trade_result

current_positions = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices = {}
last_signals = {}  # tkr -> (timestamp, direction)

initial_balance = None
last_balance = None
total_profit = 0
total_deposit = 0
total_withdrawal = 0


def get_alor_symbol(instrument: str) -> str:
    return {"CRU5": "CNY-9.25", "NGN5": "NG-7.25"}.get(instrument, instrument)


async def execute_market_order(ticker: str, side: str, qty: int):
    alor_symbol = get_alor_symbol(ticker)
    res = await place_order({
        "side": side.upper(),
        "qty": qty,
        "instrument": ticker,
        "symbol": alor_symbol
    })

    print("📥 Order sent, got response:", res)

    if "error" in res:
        await send_telegram_log(f"❌ {side}/{ticker}/{qty}: {res['error']}")
        return None

    await asyncio.sleep(0.5)
    snapshot = await get_position_snapshot(ticker)
    actual_position = snapshot.get("qty", 0)

    return {
        "price": float(res.get("price", 0)),
        "order_id": res.get("order_id", "—"),
        "position": actual_position
    }


async def process_signal(tv_tkr: str, sig: str):
    global total_profit, initial_balance, last_balance, total_deposit, total_withdrawal

    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Неизвестный тикер {tv_tkr}")
        return {"error": "Unknown ticker"}

    tkr = TICKER_MAP[tv_tkr]["trade"]
    dir_ = 1 if sig.upper() == "LONG" else -1
    side = "buy" if dir_ > 0 else "sell"
    cur = current_positions.get(tkr, 0)

    # ⏱ Игнорируем повторные сигналы в течение 10 минут
    now = time.time()
    last_entry = last_signals.get(tkr)
    if last_entry and last_entry[1] == dir_ and now - last_entry[0] < 600:
        await send_telegram_log(f"⏳ Повторный сигнал {tv_tkr}/{sig} проигнорирован (менее 10 минут)")
        return {"status": "ignored"}
    last_signals[tkr] = (now, dir_)

    # 🔁 Переворот позиции одной заявкой
    if cur * dir_ < 0:
        total_qty = abs(cur) + START_QTY[tkr]
        result = await execute_market_order(tkr, side, total_qty)
        if result:
            price = result["price"]
            actual_position = result["position"]
            prev_entry = entry_prices.get(tkr, 0)
            pnl = (price - prev_entry) * cur
            pct = (pnl / (abs(prev_entry) * abs(cur)) * 100) if prev_entry else 0

            current_balance = await asyncio.to_thread(get_current_balance)
            if initial_balance is None:
                initial_balance = current_balance
                last_balance = current_balance

            theoretical_balance = last_balance + pnl
            diff = round(current_balance - theoretical_balance, 2)
            if diff > 10:
                total_deposit += diff
            elif diff < -10:
                total_withdrawal += abs(diff)

            last_balance = current_balance
            net_investment = initial_balance + total_deposit - total_withdrawal
            total_profit += pnl

            await log_trade_result(
                ticker=tkr,
                side="LONG" if cur > 0 else "SHORT",
                qty=cur,
                entry_price=prev_entry,
                exit_price=price
            )

            current_positions[tkr] = actual_position
            entry_prices[tkr] = price
            emoji = "🔻" if pnl < 0 else "🟢"
            await send_telegram_log(
                f"{emoji} Сделка завершена:\n"
                f"Тикер: {tkr}\n"
                f"Действие: {'LONG' if cur > 0 else 'SHORT'} → {'LONG' if dir_ > 0 else 'SHORT'}\n"
                f"Контракты: {abs(total_qty)}\n"
                f"Вход: {prev_entry:.2f} → Выход: {price:.2f}\n"
                f"PnL: {pnl:+.2f} руб. ({pct:+.2f}%)\n"
                f"Баланс: {current_balance:.2f} руб."
            )
        return {"status": "flip"}

    # ➕ Усреднение
    if cur * dir_ > 0:
        new = cur + ADD_QTY[tkr]
        if abs(new) > MAX_QTY[tkr]:
            await send_telegram_log(f"🚫 Лимит {tkr}={MAX_QTY[tkr]}, пропускаем усреднение")
            return {"status": "limit"}

        result = await execute_market_order(tkr, side, ADD_QTY[tkr])
        if result:
            price = result["price"]
            entry_prices[tkr] = (
                (entry_prices.get(tkr, 0) * abs(cur) + price * ADD_QTY[tkr]) / abs(new)
            )
            current_positions[tkr] = new
            bal = await asyncio.to_thread(get_current_balance)
            await send_telegram_log(f"➕ Усреднение {tkr}={new:+} @ {entry_prices[tkr]:.2f}, 💰 {bal:.2f} ₽")
        return {"status": "avg"}

    # ✅ Открытие новой позиции
    if cur == 0:
        result = await execute_market_order(tkr, side, START_QTY[tkr])
        if result:
            price = result["price"]
            current_positions[tkr] = dir_ * START_QTY[tkr]
            entry_prices[tkr] = price
            bal = await asyncio.to_thread(get_current_balance)
            await send_telegram_log(f"✅ Открыта {tkr}={dir_ * START_QTY[tkr]:+} @ {price:.2f}, 💰 {bal:.2f} ₽")
        return {"status": "open"}

    return {"status": "noop"}
