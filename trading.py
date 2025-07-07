
import asyncio
import time
import httpx
from telegram_logger import send_telegram_log
from config import TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY, BASE_URL, ACCOUNT_ID
from auth import get_current_balance, get_access_token
from alor import place_order, get_position_snapshot
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

SIGNAL_COOLDOWN_SECONDS = 3600  # 1 час — только для RSI сигналов

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

async def get_all_positions():
    token = await get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/positions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

async def log_all_positions():
    try:
        data = await get_all_positions()
        msg = "📊 Позиции после сделки:\n"
        for pos in data:
            ticker = pos.get("symbol")
            qty = pos.get("qty", 0)
            avg_price = pos.get("averagePrice", 0.0)
            if qty != 0:
                msg += f"• {ticker}: {qty:+} @ {avg_price:.2f}\n"
        await send_telegram_log(msg)
    except Exception as e:
        await send_telegram_log(f"⚠️ Ошибка при получении позиций: {e}")

async def execute_market_order(ticker: str, side: str, qty: int):
    await send_telegram_log(f"📥 Запрос позиций перед ордером ({ticker})")
    await log_all_positions()

    alor_symbol = get_alor_symbol(ticker)
    res = await place_order({
        "side": side.upper(),
        "qty": qty,
        "instrument": ticker,
        "symbol": alor_symbol
    })

    print("📅 Order sent, got response:", res)

    if "error" in res:
        await send_telegram_log(f"❌ {side}/{ticker}/{qty}: {res['error']}")
        return None

    await asyncio.sleep(30)
    snapshot = await get_position_snapshot(ticker)
    actual_position = snapshot.get("qty", 0)

    await log_all_positions()

    return {
        "price": res.get("price", 0.0),
        "order_id": res.get("order_id", "—"),
        "position": actual_position
    }

async def process_signal(tv_tkr: str, sig: str):
    global total_profit, initial_balance, last_balance, total_deposit, total_withdrawal

    await send_telegram_log(f"📩 Обработка сигнала: {tv_tkr} / {sig}")

    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Неизвестный тикер: {tv_tkr}")
        return {"error": "Unknown ticker"}

    tkr = TICKER_MAP[tv_tkr]["trade"]
    sig_upper = sig.strip().upper()

    if sig_upper in ("RSI>70", "RSI<30"):
        now = time.time()
        signal_key = f"{tkr}:{sig_upper}"
        last_time = last_signals.get(signal_key)

        if last_time and now - last_time < SIGNAL_COOLDOWN_SECONDS:
            remaining = int(SIGNAL_COOLDOWN_SECONDS - (now - last_time))
            await send_telegram_log(f"🕓 Сигнал {sig_upper} проигнорирован ({tkr}) — Cooldown: {remaining} сек.")
            return {"status": "cooldown"}

        last_signals[signal_key] = now

        all_positions = await get_all_positions()
        cur = next((pos["qty"] for pos in all_positions if pos["symbol"] == tkr), 0)
        current_positions[tkr] = cur

        if cur == 0:
            await send_telegram_log(f"⛔ Сигнал {sig_upper} по {tkr} проигнорирован — нет открытой позиции")
            return {"status": "no_position"}

        if sig_upper == "RSI>70" and cur > 0:
            half_qty = abs(cur) // 2
            if half_qty > 0:
                result = await execute_market_order(tkr, "sell", half_qty)
                if result:
                    current_positions[tkr] = cur - half_qty
                    await send_telegram_log(
                        f"📉 RSI>70: Продажа 50% LONG по {tkr}\nКонтракты: {half_qty}\nЦена: {result['price']:.2f}"
                    )
            return {"status": "partial_long_close"}

        elif sig_upper == "RSI<30" and cur < 0:
            half_qty = abs(cur) // 2
            if half_qty > 0:
                result = await execute_market_order(tkr, "buy", half_qty)
                if result:
                    current_positions[tkr] = cur + half_qty
                    await send_telegram_log(
                        f"📈 RSI<30: Покупка 50% SHORT по {tkr}\nКонтракты: {half_qty}\nЦена: {result['price']:.2f}"
                    )
            return {"status": "partial_short_close"}

    # --- Стандартные сигналы LONG / SHORT ---
    if sig_upper not in ("LONG", "SHORT"):
        await send_telegram_log(f"⚠️ Неизвестный сигнал: {sig_upper}")
        return {"status": "invalid_signal"}

    dir_ = 1 if sig_upper == "LONG" else -1
    side = "buy" if dir_ > 0 else "sell"

    all_positions = await get_all_positions()
    cur = next((pos["qty"] for pos in all_positions if pos["symbol"] == tkr), 0)
    current_positions[tkr] = cur

    if cur * dir_ < 0:
        await send_telegram_log(f"🔄 Переворот по {tkr}: позиция {cur}, сигнал {sig_upper}")
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
                    f"{'LONG' if cur > 0 else 'SHORT'} → {'LONG' if dir_ > 0 else 'SHORT'}\n"
                    f"Контракты: {abs(total_qty)}\n"
                    f"Цена: {prev_entry:.2f} → {price:.2f}\n"
                    f"PnL: {pnl:+.2f} ₽ ({pct:+.2f}%)\n"
                    f"Баланс: {current_balance:.2f} ₽"
                )
            else:
                await send_telegram_log(
                    f"⚠️ Переворот не завершён!\n{tkr} — запрошено {total_qty}, получено {actual_position}"
                )

            summary = await get_account_summary()
            await send_balance_to_telegram(summary, total_profit, initial_balance or 1)

        return {"status": "flip"}

    if cur * dir_ > 0:
        new = cur + ADD_QTY[tkr]
        if abs(new) > MAX_QTY[tkr]:
            await send_telegram_log(f"❌ Превышен лимит по {tkr}: {abs(new)} > {MAX_QTY[tkr]}")
            return {"status": "limit_exceeded"}

        result = await execute_market_order(tkr, side, ADD_QTY[tkr])
        if result:
            price = result["price"]
            entry_prices[tkr] = (
                (entry_prices.get(tkr, 0) * abs(cur) + price * ADD_QTY[tkr]) / abs(new)
            )
            current_positions[tkr] = new
            await send_telegram_log(f"➕ Усреднение {tkr} до {new:+} @ {entry_prices[tkr]:.2f}")

            summary = await get_account_summary()
            await send_balance_to_telegram(summary, total_profit, initial_balance or 1)

        return {"status": "average"}

    if cur == 0:
        result = await execute_market_order(tkr, side, START_QTY[tkr])
        if result:
            price = result["price"]
            current_positions[tkr] = dir_ * START_QTY[tkr]
            entry_prices[tkr] = price
            await send_telegram_log(f"✅ Открыта новая позиция: {tkr} = {dir_ * START_QTY[tkr]:+} @ {price:.2f}")

            summary = await get_account_summary()
            await send_balance_to_telegram(summary, total_profit, initial_balance or 1)

        return {"status": "open"}

    return {"status": "noop"}

__all__ = ["total_profit", "initial_balance"]
