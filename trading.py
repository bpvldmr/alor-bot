import asyncio
import time
import httpx
from telegram_logger import send_telegram_log
from config import TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY, BASE_URL, ACCOUNT_ID
from auth import get_current_balance, get_access_token
from alor import place_order, get_position_snapshot, get_current_positions
from trade_logger import log_trade_result
from balance import send_balance_to_telegram

# --- Глобальные состояния ----------------------------------------------------
current_positions = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices      = {}
last_signals      = {}

initial_balance   = None
last_balance      = None
total_profit      = 0
total_deposit     = 0
total_withdrawal  = 0

SIGNAL_COOLDOWN_SECONDS = 3600            # 1 час – только для RSI

# -----------------------------------------------------------------------------


def get_alor_symbol(instrument: str) -> str:
    """Преобразует тикер TradingView в символ ALOR."""
    return {"CRU5": "CNY-9.25", "NGN5": "NG-7.25"}.get(instrument, instrument)


async def get_account_summary():
    token = await get_access_token()
    url   = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()


async def execute_market_order(ticker: str, side: str, qty: int):
    """Отправляет маркет-ордер и ждёт 30 с, чтобы получить фактическую позицию."""
    alor_symbol = get_alor_symbol(ticker)
    res = await place_order(
        {"side": side.upper(), "qty": qty, "instrument": ticker, "symbol": alor_symbol}
    )

    print("📅 Order sent, got response:", res)

    if "error" in res:
        await send_telegram_log(f"❌ {side}/{ticker}/{qty}: {res['error']}")
        return None

    await asyncio.sleep(30)
    snapshot = await get_position_snapshot(ticker)
    actual_position = snapshot.get("qty", 0)

    return {"price": res.get("price", 0.0), "order_id": res.get("order_id", "—"), "position": actual_position}


# ═════════════════════════════════════════════════════════════════════════════
#                       ОСНОВНАЯ ФУНКЦИЯ ОБРАБОТКИ СИГНАЛОВ
# ═════════════════════════════════════════════════════════════════════════════
async def process_signal(tv_tkr: str, sig: str):
    global total_profit, initial_balance, last_balance, total_deposit, total_withdrawal

    await send_telegram_log(f"📅 Обработка сигнала: {tv_tkr} / {sig}")

    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Неизвестный тикер {tv_tkr}")
        return {"error": "Unknown ticker"}

    tkr       = TICKER_MAP[tv_tkr]["trade"]
    sig_upper = sig.upper()

    # ------------------------------------------------------------------ RSI --
    if sig_upper in ("RSI>70", "RSI<30"):
        now = time.time()
        key = f"{tkr}:{sig_upper}"
        if last_signals.get(key) and now - last_signals[key] < SIGNAL_COOLDOWN_SECONDS:
            await send_telegram_log(f"⏳ Сигнал проигнорирован (cooldown): {tv_tkr}/{sig}")
            return {"status": "ignored"}
        last_signals[key] = now

        positions = await get_current_positions()
        cur = positions.get(tkr, 0)
        current_positions[tkr] = cur

        if cur == 0:
            await send_telegram_log(f"⚠️ Нет открытой позиции по {tkr}, сигнал {sig} проигнорирован")
            return {"status": "no_position"}

        if sig_upper == "RSI>70":
            if cur > 0:
                half = abs(cur) // 2
                if half:
                    res = await execute_market_order(tkr, "sell", half)
                    if res:
                        current_positions[tkr] = cur - half
                        await send_telegram_log(
                            f"📉 RSI>70: Продаём половину LONG по {tkr}\nКонтракты: {half}\nЦена: {res['price']:.2f}"
                        )
                return {"status": "partial_long_close"}
            await send_telegram_log(f"⚠️ RSI>70: У вас SHORT по {tkr}, ничего не делаем")
            return {"status": "noop"}

        if sig_upper == "RSI<30":
            if cur < 0:
                half = abs(cur) // 2
                if half:
                    res = await execute_market_order(tkr, "buy", half)
                    if res:
                        current_positions[tkr] = cur + half
                        await send_telegram_log(
                            f"📈 RSI<30: Покупаем половину SHORT по {tkr}\nКонтракты: {half}\nЦена: {res['price']:.2f}"
                        )
                return {"status": "partial_short_close"}
            await send_telegram_log(f"⚠️ RSI<30: У вас LONG по {tkr}, ничего не делаем")
            return {"status": "noop"}

    # ---------------------------------------------------- LONG0 / SHORT0 -----
    if sig_upper in ("LONG0", "SHORT0"):
        positions = await get_current_positions()
        cur = positions.get(tkr, 0)
        current_positions[tkr] = cur

        if cur == 0:
            await send_telegram_log(f"⚠️ Нет позиции по {tkr}, сигнал {sig_upper} проигнорирован")
            return {"status": "no_position"}

        # LONG0 закрывает весь SHORT, SHORT0 закрывает весь LONG
        need_close_short = sig_upper == "LONG0"  and cur < 0
        need_close_long  = sig_upper == "SHORT0" and cur > 0

        if not (need_close_short or need_close_long):
            await send_telegram_log(f"⚠️ Сигнал {sig_upper} не совпадает с направлением позиции {cur:+}")
            return {"status": "direction_mismatch"}

        side = "buy" if cur < 0 else "sell"
        qty  = abs(cur)

        res = await execute_market_order(tkr, side, qty)
        if res:
            current_positions[tkr] = 0
            entry_prices.pop(tkr, None)
            await send_telegram_log(
                f"🔒 {sig_upper}: позиция по {tkr} закрыта полностью\nКонтракты: {qty}\nЦена: {res['price']:.2f}"
            )
            summary = await get_account_summary()
            await send_balance_to_telegram(summary, total_profit, initial_balance or 1)
        return {"status": "close_all"}

    # ----------------------------------------------------- LONG / SHORT ------
    dir_  = 1 if sig_upper == "LONG"  else -1
    side  = "buy" if dir_ > 0        else "sell"

    positions = await get_current_positions()
    cur = positions.get(tkr, 0)
    current_positions[tkr] = cur

    # 1️⃣ ПЕРЕВОРОТ -----------------------------------------------------------
    if cur * dir_ < 0:
        await send_telegram_log(f"🔄 Переворот: {tkr}, сигнал {sig_upper}, позиция {cur}")
        total_qty = abs(cur) + START_QTY[tkr]
        res = await execute_market_order(tkr, side, total_qty)
        if res:
            price = res["price"]
            actual_position = res["position"]
            prev_entry = entry_prices.get(tkr, 0)
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
                ticker=tkr, side="LONG" if cur > 0 else "SHORT",
                qty=cur, entry_price=prev_entry, exit_price=price
            )

            if actual_position * dir_ > 0:           # переворот удался
                current_positions[tkr] = actual_position
                entry_prices[tkr]      = price
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
                    f"⚠️ Переворот не завершён!  Запрошено {total_qty}, позиция: {actual_position:+}"
                )

            summary = await get_account_summary()
            await send_balance_to_telegram(summary, total_profit, initial_balance or 1)

        return {"status": "flip"}

    # 2️⃣ УС­РЕД­НЕ­НИЕ -------------------------------------------------------
    if cur * dir_ > 0:
        new = cur + ADD_QTY[tkr]
        if abs(new) > MAX_QTY[tkr]:
            await send_telegram_log(f"❌ Превышен лимит по {tkr}: {MAX_QTY[tkr]}")
            return {"status": "limit"}

        res = await execute_market_order(tkr, side, ADD_QTY[tkr])
        if res:
            price = res["price"]
            entry_prices[tkr] = (
                (entry_prices.get(tkr, 0) * abs(cur) + price * ADD_QTY[tkr]) / abs(new)
            )
            current_positions[tkr] = new
            await send_telegram_log(
                f"➕ Усреднение {tkr}={new:+} @ {entry_prices[tkr]:.2f}"
            )

            summary = await get_account_summary()
            await send_balance_to_telegram(summary, total_profit, initial_balance or 1)

        return {"status": "avg"}

    # 3️⃣ ОТ­КРЫ­ТИЕ ----------------------------------------------------------
    if cur == 0:
        res = await execute_market_order(tkr, side, START_QTY[tkr])
        if res:
            price = res["price"]
            current_positions[tkr] = dir_ * START_QTY[tkr]
            entry_prices[tkr]      = price
            await send_telegram_log(
                f"✅ Открыта {tkr}={dir_ * START_QTY[tkr]:+} @ {price:.2f}"
            )

            summary = await get_account_summary()
            await send_balance_to_telegram(summary, total_profit, initial_balance or 1)

        return {"status": "open"}

    return {"status": "noop"}


# -----------------------------------------------------------------------------    
__all__ = ["total_profit", "initial_balance"]
