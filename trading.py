import asyncio
from telegram_logger import send_telegram_log
from config import TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY
from auth import get_current_balance
from alor import place_order
from trade_logger import log_trade_result

current_positions = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices = {}

# Финансовые переменные
initial_balance = None
last_balance = None
total_profit = 0
total_deposit = 0
total_withdrawal = 0

def get_alor_symbol(instrument: str) -> str:
    if instrument == "CRU5":
        return "CNY-9.25"
    elif instrument == "NGN5":
        return "NG-7.25"
    return instrument

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

    price = float(res.get("price", 0))
    order_id = res.get("order_id", "—")
    await send_telegram_log(f"✅ {side}/{ticker}/{qty} исполнена @ {price:.2f} ₽ (ID {order_id})")
    return price

async def close_position(ticker: str):
    global total_profit, initial_balance, last_balance, total_deposit, total_withdrawal

    qty = current_positions.get(ticker, 0)
    if qty == 0:
        return

    side = "sell" if qty > 0 else "buy"
    fill_price = await execute_market_order(ticker, side, abs(qty))
    if fill_price is None:
        return

    entry = entry_prices.get(ticker, 0)
    pnl = (fill_price - entry) * qty
    pct = (pnl / (entry * abs(qty)) * 100) if entry else 0
    current_positions[ticker] = 0
    total_profit += pnl

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
    roi = (total_profit / net_investment * 100) if net_investment else 0

    await log_trade_result(
        ticker=ticker,
        side="LONG" if qty > 0 else "SHORT",
        qty=qty,
        entry_price=entry,
        exit_price=fill_price
    )

async def process_signal(tv_tkr: str, sig: str):
    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Неизвестный тикер {tv_tkr}")
        return {"error": "Unknown ticker"}

    tkr = TICKER_MAP[tv_tkr]["trade"]
    dir_ = 1 if sig.upper() == "LONG" else -1
    side = "buy" if sig.upper() == "LONG" else "sell"
    cur = current_positions.get(tkr, 0)

    if cur * dir_ > 0:
        new = cur + ADD_QTY[tkr]
        if abs(new) > MAX_QTY[tkr]:
            await send_telegram_log(f"🚫 Лимит {tkr}={MAX_QTY[tkr]}, пропускаем усреднение")
            return {"status": "limit"}

        price = await execute_market_order(tkr, side, ADD_QTY[tkr])
        if price is not None:
            entry_prices[tkr] = (
                (entry_prices.get(tkr, 0) * abs(cur) + price * ADD_QTY[tkr]) / abs(new)
            )
            current_positions[tkr] = new
            bal = await asyncio.to_thread(get_current_balance)
            await send_telegram_log(f"➕ Усреднение {tkr}={new:+} @ {entry_prices[tkr]:.2f}, 💰 {bal:.2f} ₽")
        return {"status": "avg"}

    if cur * dir_ < 0:
        await close_position(tkr)
        sq = START_QTY[tkr]
        price = await execute_market_order(tkr, side, sq)
        if price is not None:
            current_positions[tkr] = dir_ * sq
            entry_prices[tkr] = price
            bal = await asyncio.to_thread(get_current_balance)
            await send_telegram_log(f"🔄 Новая {tkr}={dir_ * sq:+} @ {price:.2f}, 💰 {bal:.2f} ₽")
        return {"status": "flip"}

    if cur == 0:
        sq = START_QTY[tkr]
        price = await execute_market_order(tkr, side, sq)
        if price is not None:
            current_positions[tkr] = dir_ * sq
            entry_prices[tkr] = price
            bal = await asyncio.to_thread(get_current_balance)
            await send_telegram_log(f"✅ Открыта {tkr}={dir_ * sq:+} @ {price:.2f}, 💰 {bal:.2f} ₽")
        return {"status": "open"}

    return {"status": "noop"}
