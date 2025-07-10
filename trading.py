# trading.py
# ─────────────────────────────────────────────────────────────────────────────
# Логика сигналов
# • TPL / TPS            – take-profit сигналы от TradingView
#       * CNY-9.25  → позиция закрывается полностью
#       * NG-7.25   → закрывается ровно половина
# • RSI>80 / RSI<20      – если позиции нет → открывает ½ старт-лота,
#                          если позиция противоположная → flip (+½ старт-лота)
# • RSI>70 / RSI<30      – 1-часовой cool-down; 1-й сигнал закрывает ½ позиции,
#                          2-й (если не было flip) закрывает остаток
# • LONG / SHORT         – flip / усреднение / открытие с лимитом MAX_QTY
# • При клиринге («ExchangeUndefinedError») заявка повторяется 3 раза
#   с паузой 5 мин.
# ─────────────────────────────────────────────────────────────────────────────

import asyncio, time, httpx
from telegram_logger import send_telegram_log
from config import (
    TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY
)
from auth        import get_current_balance
from alor        import place_order, get_position_snapshot, get_current_positions
from trade_logger import log_trade_result
from balance      import send_balance_to_telegram

# ────────────────────────── Глобальные состояния ────────────────────────────
current_positions         = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices: dict[str,float] = {}
last_signals: dict[str,float] = {}          # key (sym:rsiX) → timestamp
rsi_state:   dict[str,dict]   = {}          # key → {"count":1,"dir":±1}

initial_balance = last_balance = None
total_profit = total_deposit = total_withdrawal = 0

SIGNAL_COOLDOWN_SECONDS = 3600              # 1-часовой cool-down для RSI
# ─────────────────────────────────────────────────────────────────────────────


async def execute_market_order(
    symbol: str,
    side:   str,
    qty:    int,
    *,
    max_retries: int = 3,
    delay_sec:   int = 300
):
    """
    Отправляет маркет-ордер. Если биржа отвечает 400 / ExchangeUndefinedError
    («идёт клиринг» или «цена сделки вне лимита»), повторяет попытку.
    """
    attempt = 1
    while attempt <= max_retries:
        res = await place_order({
            "side": side.upper(),
            "qty":  qty,
            "instrument": symbol,
            "symbol":     symbol
        })

        if "error" in res:
            err = str(res["error"])
            if ("ExchangeUndefinedError" in err
                    and ("клиринг" in err.lower() or "price" in err.lower())):
                await send_telegram_log(
                    f"⏳ {symbol}: клиринг / лимит-price, retry "
                    f"{attempt}/{max_retries} через {delay_sec//60} мин"
                )
                attempt += 1
                await asyncio.sleep(delay_sec)
                continue
            await send_telegram_log(f"❌ {side}/{symbol}/{qty}: {err}")
            return None

        # успешная заявка
        await asyncio.sleep(30)
        snap = await get_position_snapshot(symbol)
        return {
            "price":    res.get("price", 0.0),
            "position": snap.get("qty", 0)
        }

    await send_telegram_log(
        f"⚠️ {symbol}: ордер не выполнен после {max_retries} попыток (клиринг)"
    )
    return None


# ═══════════════════════════ process_signal ══════════════════════════════════
async def process_signal(tv_tkr: str, sig: str):
    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Unknown ticker {tv_tkr}")
        return {"error": "Unknown ticker"}

    symbol    = TICKER_MAP[tv_tkr]["trade"]     # CNY-9.25 / NG-7.25
    sig_upper = sig.upper()

    # ──────────────────── TPL / TPS ──────────────────────────────────────────
    if sig_upper in ("TPL", "TPS"):
        positions = await get_current_positions()
        cur = positions.get(symbol, 0)

        if cur == 0:
            await send_telegram_log(f"⚠️ {sig_upper}: no position in {symbol}")
            return {"status": "no_position"}

        if sig_upper == "TPL":    # закрываем long
            if cur <= 0:
                await send_telegram_log("⚠️ TPL but no LONG position")
                return {"status": "dir_mismatch"}
            qty_close = abs(cur) if symbol == "CNY-9.25" else max(cur//2, 1)
            res = await execute_market_order(symbol, "sell", qty_close)
            if res:
                current_positions[symbol] = cur - qty_close
                if current_positions[symbol] == 0:
                    entry_prices.pop(symbol, None)
                await send_telegram_log(
                    f"💰 TPL: closed {qty_close} of {cur} on {symbol} "
                    f"@ {res['price']:.2f}"
                )
            return {"status": "tpl_done"}

        if sig_upper == "TPS":    # закрываем short
            if cur >= 0:
                await send_telegram_log("⚠️ TPS but no SHORT position")
                return {"status": "dir_mismatch"}
            qty_close = abs(cur) if symbol == "CNY-9.25" else max(abs(cur)//2,1)
            res = await execute_market_order(symbol, "buy", qty_close)
            if res:
                current_positions[symbol] = cur + qty_close
                if current_positions[symbol] == 0:
                    entry_prices.pop(symbol, None)
                await send_telegram_log(
                    f"💰 TPS: closed {qty_close} of {abs(cur)} on {symbol} "
                    f"@ {res['price']:.2f}"
                )
            return {"status": "tps_done"}

    # ──────────────────── RSI>80 / RSI<20 ────────────────────────────────────
    if sig_upper in ("RSI>80", "RSI<20"):
        now = time.time()
        key = f"{symbol}:{sig_upper}"
        if key in last_signals and now - last_signals[key] < SIGNAL_COOLDOWN_SECONDS:
            await send_telegram_log("⏳ RSI80/20 ignored (cool-down)")
            return {"status": "ignored"}
        last_signals[key] = now

        positions = await get_current_positions()
        cur = positions.get(symbol, 0)
        half_start = max(START_QTY[symbol] // 2, 1)

        want_short = sig_upper == "RSI>80"
        want_long  = sig_upper == "RSI<20"

        # позиция 0 → открываем
        if cur == 0:
            side = "sell" if want_short else "buy"
            res  = await execute_market_order(symbol, side, half_start)
            if res:
                new_pos = -half_start if want_short else half_start
                current_positions[symbol] = new_pos
                entry_prices[symbol]      = res["price"]
                await send_telegram_log(
                    f"🚀 {sig_upper}: open "
                    f"{'SHORT' if want_short else 'LONG'} {half_start} @ {res['price']:.2f}"
                )
            return {"status": "rsi80_20_open"}

        # противоположная позиция → переворот (+½ старт-лота)
        if (want_short and cur > 0) or (want_long and cur < 0):
            side = "sell" if cur > 0 else "buy"
            qty_flip = abs(cur) + half_start
            res = await execute_market_order(symbol, side, qty_flip)
            if res:
                prev_entry = entry_prices.get(symbol, 0)
                pnl = (res["price"] - prev_entry) * cur
                await log_trade_result(symbol, "LONG" if cur>0 else "SHORT",
                                       cur, prev_entry, res["price"])

                new_pos = -half_start if side == "sell" else half_start
                current_positions[symbol] = new_pos
                entry_prices[symbol]      = res["price"]
                await send_telegram_log(
                    f"🔄 {sig_upper}: flip {symbol} → new {new_pos:+}, "
                    f"pnl closed leg {pnl:+.2f}"
                )
            return {"status": "rsi80_20_flip"}

        # уже в ту же сторону
        await send_telegram_log(f"⚠️ {sig_upper}: already aligned, no action")
        return {"status": "noop_rsi80_20"}

    # ──────────────────── RSI>70 / RSI<30 ────────────────────────────────────
    if sig_upper in ("RSI>70", "RSI<30"):
        now = time.time()
        key = f"{symbol}:{sig_upper}"
        if key in last_signals and now - last_signals[key] < SIGNAL_COOLDOWN_SECONDS:
            await send_telegram_log("⏳ RSI70/30 ignored (cool-down)")
            return {"status": "ignored"}
        last_signals[key] = now

        positions = await get_current_positions()
        cur = positions.get(symbol, 0)
        if cur == 0:
            await send_telegram_log("⚠️ RSI70/30: no position")
            return {"status": "no_position"}

        want_sell = sig_upper == "RSI>70" and cur > 0
        want_buy  = sig_upper == "RSI<30" and cur < 0
        if not (want_sell or want_buy):
            await send_telegram_log("⚠️ RSI70/30: dir mismatch")
            return {"status": "noop"}

        side = "sell" if want_sell else "buy"
        state = rsi_state.get(key, {"count":0,"dir":0})
        same_dir = state["dir"] == (1 if cur>0 else -1)

        if state["count"] == 0 or not same_dir:
            qty_close = max(abs(cur)//2, 1)
            rsi_state[key] = {"count":1,"dir":1 if cur>0 else -1}
            part = "½"
        else:
            qty_close = abs(cur)
            rsi_state.pop(key, None)
            part = "rest"

        res = await execute_market_order(symbol, side, qty_close)
        if res:
            current_positions[symbol] = cur - qty_close if side=="sell" else cur+qty_close
            if current_positions[symbol] == 0:
                entry_prices.pop(symbol, None)
            await send_telegram_log(
                f"🔔 {sig_upper}: close {part} {qty_close} @ {res['price']:.2f}"
            )
        return {"status": "rsi70_30_close"}

    # ──────────────────── LONG / SHORT ───────────────────────────────────────
    if sig_upper not in ("LONG", "SHORT"):
        await send_telegram_log(f"⚠️ Unknown action {sig_upper}")
        return {"status": "invalid_action"}

    dir_  = 1 if sig_upper == "LONG" else -1
    side  = "buy" if dir_>0 else "sell"
    positions = await get_current_positions()
    cur = positions.get(symbol, 0)

    # flip
    if cur * dir_ < 0:
        total_qty = abs(cur) + START_QTY[symbol]
        res = await execute_market_order(symbol, side, total_qty)
        if res:
            # сбрасываем rsi-счётчики
            for k in list(rsi_state):
                if k.startswith(symbol+":"): rsi_state.pop(k, None)
            for k in list(last_signals):
                if k.startswith(symbol+":"): last_signals.pop(k, None)
            current_positions[symbol] = dir_ * START_QTY[symbol]
            entry_prices[symbol]      = res["price"]
            await send_telegram_log(f"🟢 flip {symbol} → {current_positions[symbol]:+}")
        return {"status": "flip"}

    # averaging
    if cur * dir_ > 0:
        new = cur + ADD_QTY[symbol]
        if abs(new) > MAX_QTY[symbol]:
            await send_telegram_log(f"❌ {symbol}: max qty {MAX_QTY[symbol]}")
            return {"status": "limit"}
        res = await execute_market_order(symbol, side, ADD_QTY[symbol])
        if res:
            current_positions[symbol] = new
            await send_telegram_log(
                f"➕ avg {symbol}: new pos {new:+} @ {res['price']:.2f}"
            )
        return {"status": "avg"}

    # open
    if cur == 0:
        res = await execute_market_order(symbol, side, START_QTY[symbol])
        if res:
            current_positions[symbol] = dir_ * START_QTY[symbol]
            entry_prices[symbol]      = res["price"]
            await send_telegram_log(
                f"✅ open {symbol} {current_positions[symbol]:+} @ {res['price']:.2f}"
            )
        return {"status": "open"}

    return {"status": "noop"}


__all__ = ["total_profit", "initial_balance"]
