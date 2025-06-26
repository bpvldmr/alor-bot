import asyncio
from datetime import datetime, time
import pytz
from telegram_logger import send_telegram_log
from config import TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY
from auth import get_current_balance
from alor import place_order

current_positions = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices = {}

# 🔢 Финансовые переменные
initial_balance = None
last_balance = None
total_profit = 0
total_deposit = 0
total_withdrawal = 0

def is_weekend() -> bool:
    return datetime.utcnow().weekday() in (5, 6)

def is_trading_hours() -> bool:
    tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(tz)
    return now.weekday() < 5 and time(9, 0) <= now.time() <= time(23, 0)

async def execute_market_order(ticker: str, side: str, qty: int):
    res = await asyncio.to_thread(place_order, {
        "side": side.upper(),
        "qty": qty,
        "instrument": ticker
    })
    if "error" in res:
        send_telegram_log(f"❌ {side}/{ticker}/{qty}: {res['error']}")
        return None

    price = float(res.get("price", 0))
    order_id = res.get("order_id", "—")
    send_telegram_log(f"✅ {side}/{ticker}/{qty} исполнена @ {price:.2f} ₽ (ID {order_id})")
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
    pct = pnl / (entry * abs(qty)) * 100 if entry else 0
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
        note = f"🟢 Ввод средств: +{diff:.2f} ₽"
    elif diff < -10:
        total_withdrawal += abs(diff)
        note = f"🔴 Вывод средств: -{abs(diff):.2f} ₽"
    else:
        note = "—"

    last_balance = current_balance
    net_investment = initial_balance + total_deposit - total_withdrawal
    roi = (total_profit / net_investment * 100) if net_investment else 0

    send_telegram_log(
        f"❌ Закрыта {ticker} {qty:+} @ {fill_price:.2f} ₽\n"
        f"📊 PnL {pnl:+.2f} ₽ ({pct:+.2f}%)\n"
        f"💰 Баланс: {current_balance:.2f} ₽  | {note}\n"
        f"📈 Общая прибыль: {total_profit:+.2f} ₽\n"
        f"💼 Доходность на капитал: {roi:+.2f}%"
    )

async def handle_trading_signal(tv_tkr: str, sig: str):
    if is_weekend():
        send_telegram_log(f"⛔ Weekend — пропускаем {sig} по {tv_tkr}")
        return {"error": "Weekend"}

    if not is_trading_hours():
        send_telegram_log(f"⏰ Вне торговых часов — пропускаем {sig} по {tv_tkr}")
        return {"error": "Out of trading hours"}

    if tv_tkr not in TICKER_MAP:
        send_telegram_log(f"⚠️ Неизвестный тикер {tv_tkr}")
        return {"error": "Unknown ticker"}

    tkr = TICKER_MAP[tv_tkr]["trade"]
    dir_ = 1 if sig.upper() == "LONG" else -1
    cur = current_positions.get(tkr, 0)

    if cur * dir_ > 0:
        new = cur + ADD_QTY[tkr]
        if abs(new) > MAX_QTY[tkr]:
            send_telegram_log(f"🚫 Лимит {tkr}={MAX_QTY[tkr]}, пропускаем усреднение")
            return {"status": "limit"}

        price = await execute_market_order(tkr, sig.lower(), ADD_QTY[tkr])
        if price is not None:
            entry_prices[tkr] = (
                (entry_prices.get(tkr, 0) * abs(cur) + price * ADD_QTY[tkr]) / abs(new)
            )
            current_positions[tkr] = new
            bal = await asyncio.to_thread(get_current_balance)
            send_telegram_log(f"➕ Усреднение {tkr}={new:+} @ {entry_prices[tkr]:.2f}, 💰 {bal:.2f} ₽")
        return {"status": "avg"}

    if cur * dir_ < 0:
        await close_position(tkr)
        sq = START_QTY[tkr]
        price = await execute_market_order(tkr, sig.lower(), sq)
        if price is not None:
            current_positions[tkr] = dir_ * sq
            entry_prices[tkr] = price
            bal = await asyncio.to_thread(get_current_balance)
            send_telegram_log(f"🔄 Новая {tkr}={dir_*sq:+} @ {price:.2f}, 💰 {bal:.2f} ₽")
        return {"status": "flip"}

    if cur == 0:
        sq = START_QTY[tkr]
        price = await execute_market_order(tkr, sig.lower(), sq)
        if price is not None:
            current_positions[tkr] = dir_ * sq
            entry_prices[tkr] = price
            bal = await asyncio.to_thread(get_current_balance)
            send_telegram_log(f"✅ Открыта {tkr}={dir_*sq:+} @ {price:.2f}, 💰 {bal:.2f} ₽")
        return {"status": "open"}

    return {"status": "noop"}

process_signal = handle_trading_signal
