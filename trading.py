import asyncio
import time
import httpx
from telegram_logger import send_telegram_log
from config import TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY, BASE_URL, ACCOUNT_ID
from auth import get_current_balance, get_access_token
from alor import place_order, get_position_snapshot, get_last_trade_price, get_current_positions
from trade_logger import log_trade_result
from balance import send_balance_to_telegram

current_positions = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices = {}
last_signals = {}

initial_balance = None
last_balance = None
total_profit = 0
total_deposit = 0
total_withdrawal = 0

def get_alor_symbol(instrument: str) -> str:
    return {"CRU5": "CNY-9.25", "NGN5": "NG-7.25"}.get(instrument, instrument)

async def get_account_summary():
    token = await get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

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

    await asyncio.sleep(2)
    last_trade_price = await get_last_trade_price(ticker)

    await asyncio.sleep(30)
    snapshot = await get_position_snapshot(ticker)
    actual_position = snapshot.get("qty", 0)

    return {
        "price": last_trade_price,
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

    positions_snapshot = await get_current_positions()
    cur = positions_snapshot.get(tkr, 0)
    current_positions[tkr] = cur

    now = time.time()
    last_entry = last_signals.get(tkr)
    if last_entry and last_entry[1] == dir_ and now - last_entry[0] < 600:
        await send_telegram_log(f"⏳ Повторный сигнал {tv_tkr}/{sig} проигнорирован")
        return {"status": "ignored"}

    last_signals[tkr] = (now, dir_)

    # 🔁 Переворот
    if cur * dir_ < 0:
        total_qty = abs(cur) + START_QTY[tkr]
        result = await execute_market_order(tkr, side, total_qty)
        if result:
            price = result["price"]
            actual_position = result["position"]
            prev_entry = entry_prices.get(tkr, 0)
            pnl = (price - prev_entry) * cur
            pct = (pnl / (abs(prev_entry) * abs(cur)) * 100) if prev_entry else 0

            current_balance = await get_current_balance()
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
            total_profit += pnl

            await log_trade_result(
                ticker=tkr,
                side="LONG" if cur > 0 else "SHORT",
                qty=cur,
                entry_price=prev_entry,
                exit_price=price
            )

            if actual_position * dir_ > 0:
                current_positions[tkr] = actual_position
                entry_prices[tkr] = price
                emoji = "🔻" if pnl < 0 else "🟢"
                await send_telegram_log(
                    f"{emoji} Переворот завершён:\n"
                    f"Тикер: {tkr}\n"
                    f"Действие: {'LONG' if cur > 0 else 'SHORT'} → {'LONG' if dir_ > 0 else 'SHORT'}\n"
                    f"Контракты: {abs(total_qty)}\n"
                    f"Вход: {prev_entry:.2f} → Выход: {price:.2f}\n"
                    f"PnL: {pnl:+.2f} руб. ({pct:+.2f}%)\n"
                    f"Баланс: {current_balance:.2f} руб."
                )
            else:
                await send_telegram_log(
                    f"⚠️ Переворот не завершён! Позиция не открыта.\n"
                    f"Тикер: {tkr}, запрошено {total_qty} контрактов.\n"
                    f"Текущая позиция после сделки: {actual_position:+}."
                )

            summary = await get_account_summary()
            await send_balance_to_telegram(summary)

        return {"status": "flip"}

    # ➕ Усреднение
    if cur * dir_ > 0:
        new = cur + ADD_QTY[tkr]
        if abs(new) > MAX_QTY[tkr]:
            await send_telegram_log(f"🚫 Лимит {tkr}={MAX_QTY[tkr]}, пропущаем усреднение")
            return {"status": "limit"}

        result = await execute_market_order(tkr, side, ADD_QTY[tkr])
        if result:
            price = result["price"]
            entry_prices[tkr] = (
                (entry_prices.get(tkr, 0) * abs(cur) + price * ADD_QTY[tkr]) / abs(new)
            )
            current_positions[tkr] = new
            await send_telegram_log(f"➕ Усреднение {tkr}={new:+} @ {entry_prices[tkr]:.2f}")

            summary = await get_account_summary()
            await send_balance_to_telegram(summary)

        return {"status": "avg"}

    # ✅ Первичное открытие
    if cur == 0:
        result = await execute_market_order(tkr, side, START_QTY[tkr])
        if result:
            price = result["price"]
            current_positions[tkr] = dir_ * START_QTY[tkr]
            entry_prices[tkr] = price
            await send_telegram_log(f"✅ Открыта {tkr}={dir_ * START_QTY[tkr]:+} @ {price:.2f}")

            summary = await get_account_summary()
            await send_balance_to_telegram(summary)

        return {"status": "open"}

    return {"status": "noop"}

__all__ = ["total_profit", "initial_balance"]
