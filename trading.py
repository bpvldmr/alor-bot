from datetime import datetime
from telegram_logger import send_telegram_log
from config import TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY
from alor import place_order
from balance import get_current_balance

# Текущие позиции (контракты) и цены входа
current_positions = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices     = {}

def is_weekend() -> bool:
    return datetime.utcnow().weekday() in (5,6)

async def execute_market_order(ticker:str, side:str, qty:int):
    res = await place_order({"side":side.upper(), "qty":qty, "instrument":ticker})
    if "error" in res:
        send_telegram_log(f"❌ {side}/{ticker}/{qty}: {res['error']}")
        return None
    send_telegram_log(f"✅ {side}/{ticker}/{qty} @ {res['price']:.2f} ₽  (ID {res['order_id']})")
    return float(res["price"])

async def close_position(ticker:str):
    qty = current_positions[ticker]
    if not qty:
        return
    side = "sell" if qty>0 else "buy"
    price= await execute_market_order(ticker, side, abs(qty))
    if price is None: 
        return
    entry = entry_prices.get(ticker,0)
    pnl   = (price - entry)*qty
    pct   = pnl/(entry*abs(qty))*100 if entry else 0
    current_positions[ticker]=0
    bal = await get_current_balance()
    send_telegram_log(
        f"❌ Закрытие {ticker}:{qty:+} @ {price:.2f} ₽\n"
        f"📊 PnL {pnl:+.2f} ₽ ({pct:+.2f}%)\n💰 Баланс {bal:.2f} ₽"
    )

async def handle_trading_signal(tv_tkr:str, sig:str):
    """
    Вход: tv_tkr="MOEX:CRU2025", sig="LONG"/"SHORT"
    """
    if is_weekend():
        send_telegram_log(f"⛔ Weekend, сигнал {sig} по {tv_tkr} пропущен")
        return {"error":"Weekend"}

    if tv_tkr not in TICKER_MAP:
        send_telegram_log(f"⚠️ Неизвестный тикер {tv_tkr}")
        return {"error":"Unknown ticker"}

    tkr  = TICKER_MAP[tv_tkr]["trade"]
    dir_ = 1 if sig=="LONG" else -1
    cur  = current_positions[tkr]

    # 1) Усреднение
    if cur*dir_ > 0:
        new = cur + ADD_QTY[tkr]
        if abs(new)>MAX_QTY[tkr]:
            send_telegram_log(f"🚫 Лимит {tkr}={MAX_QTY[tkr]}, усреднение пропущено")
            return {"error":"Limit"}
        price= await execute_market_order(tkr, sig.lower(), ADD_QTY[tkr])
        if price:
            # обновляем средневзвешенно
            entry_prices[tkr] = (
                (entry_prices.get(tkr,0)*abs(cur) + price*ADD_QTY[tkr])
                / abs(new)
            )
            current_positions[tkr] = new
            bal = await get_current_balance()
            send_telegram_log(f"➕ Усреднение {tkr}={new:+} @ {entry_prices[tkr]:.2f}, 💰 {bal:.2f} ₽")
        return {"status":"avg"}

    # 2) Встречный сигнал
    if cur*dir_ < 0:
        await close_position(tkr)
        sq = START_QTY[tkr]
        price = await execute_market_order(tkr, sig.lower(), sq)
        if price:
            current_positions[tkr] = dir_*sq
            entry_prices[tkr]     = price
            bal = await get_current_balance()
            send_telegram_log(f"🔄 Новая {tkr}={dir_*sq:+} @ {price:.2f}, 💰 {bal:.2f} ₽")
        return {"status":"flip"}

    # 3) Нет позиции
    if cur==0:
        sq = START_QTY[tkr]
        price = await execute_market_order(tkr, sig.lower(), sq)
        if price:
            current_positions[tkr] = dir_*sq
            entry_prices[tkr]     = price
            bal = await get_current_balance()
            send_telegram_log(f"✅ Открыта {tkr}={dir_*sq:+} @ {price:.2f}, 💰 {bal:.2f} ₽")
        return {"status":"open"}

    return {"status":"noop"}
