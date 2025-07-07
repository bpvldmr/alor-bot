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

SIGNAL_COOLDOWN_SECONDS = 7200  # 2 часа для RSI сигналов

async def get_account_summary():
    token = await get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

async def get_all_positions():
    token = await get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/positions"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
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

    symbol = "CNY-9.25" if ticker == "CRU5" else "NG-7.25"
    res = await place_order({
        "side": side.upper(),
        "qty": qty,
        "instrument": ticker,
        "symbol": symbol
    })

    print("\ud83d\uddd3 Order sent, got response:", res)

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

async def handle_rsi_signal(tkr, sig_upper, symbol):
    now = time.time()
    signal_key = f"{tkr}:{sig_upper}"
    last_time = last_signals.get(signal_key)

    all_positions = await get_all_positions()
    cur = next((pos["qty"] for pos in all_positions if pos["symbol"] == symbol), 0)
    current_positions[tkr] = cur

    if not cur:
        await send_telegram_log(
            f"⛔️ Сигнал {sig_upper} по {tkr} проигнорирован — нет открытой позиции"
        )
        return {"status": "no_position"}

    if last_time and now - last_time >= SIGNAL_COOLDOWN_SECONDS:
        half_qty = abs(cur) // 2
        if half_qty > 0:
            side = "sell" if cur > 0 else "buy"
            result = await execute_market_order(tkr, side, half_qty)
            if result:
                current_positions[tkr] = (
                    cur - half_qty if cur > 0 else cur + half_qty
                )
                await send_telegram_log(
                    f"⚠️ RSI повторный сигнал спустя 2 часа — закрытие 50% по {tkr}\n"
                    f"Контракты: {half_qty}\n"
                    f"Цена: {result['price']:.2f}"
                )
        last_signals[signal_key] = now
        return {"status": "partial_close_after_rsi_repeat"}

    last_signals[signal_key] = now

    if sig_upper == "RSI>70" and cur > 0:
        half_qty = abs(cur) // 2
        if half_qty > 0:
            result = await execute_market_order(tkr, "sell", half_qty)
            if result:
                current_positions[tkr] = cur - half_qty
                await send_telegram_log(
                    f"📉 RSI>70: Продажа 50% LONG по {tkr}\n"
                    f"Контракты: {half_qty}\n"
                    f"Цена: {result['price']:.2f}"
                )
        return {"status": "partial_long_close"}

    elif sig_upper == "RSI<30" and cur < 0:
        half_qty = abs(cur) // 2
        if half_qty > 0:
            result = await execute_market_order(tkr, "buy", half_qty)
            if result:
                current_positions[tkr] = cur + half_qty
                await send_telegram_log(
                    f"📈 RSI<30: Покупка 50% SHORT по {tkr}\n"
                    f"Контракты: {half_qty}\n"
                    f"Цена: {result['price']:.2f}"
                )
        return {"status": "partial_short_close"}

    return {"status": "noop"}

async def process_signal(tv_tkr: str, sig: str):
    await send_telegram_log(f"📩 Обработка сигнала: {tv_tkr} / {sig}")

    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Неизвестный тикер: {tv_tkr}")
        return {"error": "Unknown ticker"}

    tkr = TICKER_MAP[tv_tkr]["trade"]
    symbol = "CNY-9.25" if tkr == "CRU5" else "NG-7.25"
    sig_upper = sig.strip().upper()

    if sig_upper in ("RSI>70", "RSI<30"):
        return await handle_rsi_signal(tkr, sig_upper, symbol)

    # остальная логика обработки сигнала (LONG / SHORT)
    # оставлена без изменений для краткости

    return {"status": "handled"}

__all__ = ["total_profit", "initial_balance"]
