# trading.py
# ─────────────────────────────────────────────────────────────────────────────
#   *** 2025-07-14 patch-3  ***
#
#   Изменения:
#   ▸ Сигналы TPL / TPS теперь закрывают **половину позиции** для
#       • CNY-9.25
#       • NG-7.25
#     (минимум 1 контракт при объёме 1).
#
#   ▸ Cool-down и блокировка RSI-70/30 после TP — без изменений
#   ▸ Логика RSI-80/20, LONG/SHORT — без изменений
# ─────────────────────────────────────────────────────────────────────────────

import asyncio, time
from telegram_logger import send_telegram_log
from config import TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY
from alor   import place_order, get_position_snapshot, get_current_positions

# ──────────── глобальные состояния ──────────────────────────────────────────
current_positions            = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices:      dict[str, float] = {}

last_rsi_signal:   dict[str, float] = {}   # "SYM:RSI>70"
last_tp_signal:    dict[str, float] = {}   # "SYM:TPL" / "SYM:TPS"
tp_block_until:    dict[str, float] = {}   # "SYM" → ts  (блок RSI-70/30)

RSI_COOLDOWN_SEC  = 60 * 60                       # 1 ч
TP_COOLDOWN_SEC   = {"CNY-9.25": 30 * 60,
                     "NG-7.25" : 15 * 60}
TP_BLOCK_SEC      = {"CNY-9.25": 30 * 60,
                     "NG-7.25" : 10 * 60}

# ───────── util: маркет-ордер с retry при клиринге ──────────────────────────
async def execute_market_order(sym: str, side: str, qty: int,
                               *, retries: int = 3, delay: int = 300):
    for attempt in range(1, retries + 1):
        res = await place_order({"side": side.upper(),
                                 "qty":  qty,
                                 "instrument": sym,
                                 "symbol":     sym})
        if "error" in res:
            err = str(res["error"])
            if "ExchangeUndefinedError" in err and "клиринг" in err.lower():
                await send_telegram_log(
                    f"⏳ {sym}: clearing, retry {attempt}/{retries}")
                await asyncio.sleep(delay)
                continue
            await send_telegram_log(f"❌ order {side}/{sym}/{qty}: {err}")
            return None

        await asyncio.sleep(30)                         # дождаться фактического qty
        snap = await get_position_snapshot(sym)
        return {"price": res.get("price", 0.0),
                "position": snap.get("qty", 0)}
    await send_telegram_log(f"⚠️ {sym}: clearing retries exceeded")
    return None

# ═════════════════════ main entry point ═════════════════════════════════════
async def process_signal(tv_tkr: str, sig: str):
    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Unknown ticker {tv_tkr}")
        return {"error": "Unknown ticker"}

    sym       = TICKER_MAP[tv_tkr]["trade"]       # CNY-9.25 / NG-7.25
    sig_upper = sig.upper()
    now       = time.time()

    # ─────────────────────────────── TP ─────────────────────────────────────
    if sig_upper in ("TPL", "TPS"):
        cd = TP_COOLDOWN_SEC[sym]
        if now - last_tp_signal.get(f"{sym}:{sig_upper}", 0) < cd:
            await send_telegram_log(f"⏳ {sig_upper} ignored ({cd//60} min CD)")
            return {"status": "tp_cooldown"}
        last_tp_signal[f"{sym}:{sig_upper}"] = now

        pos = (await get_current_positions()).get(sym, 0)
        if pos == 0:
            await send_telegram_log("⚠️ TP but no position")
            return {"status": "no_position"}

        if (sig_upper == "TPL" and pos <= 0) or (sig_upper == "TPS" and pos >= 0):
            await send_telegram_log("⚠️ TP direction mismatch")
            return {"status": "dir_mismatch"}

        side = "sell" if pos > 0 else "buy"

        # ▸ теперь для всех инструментов закрываем **половину** позиции
        qty = max(abs(pos) // 2, 1)

        res = await execute_market_order(sym, side, qty)
        if res:
            current_positions[sym] = pos - qty if side == "sell" else pos + qty
            if current_positions[sym] == 0:
                entry_prices.pop(sym, None)
            await send_telegram_log(
                f"💰 {sig_upper} {sym}: closed {qty} @ {res['price']:.2f}")

            # блокируем RSI-70/30
            tp_block_until[sym] = now + TP_BLOCK_SEC[sym]
        return {"status": "tp_done"}

    # ───────────────────────── RSI >80 / <20 ────────────────────────────────
    if sig_upper in ("RSI>80", "RSI<20"):
        key = f"{sym}:{sig_upper}"
        if now - last_rsi_signal.get(key, 0) < RSI_COOLDOWN_SEC:
            return {"status": "rsi_cooldown"}
        last_rsi_signal[key] = now

        pos  = (await get_current_positions()).get(sym, 0)
        half = max(START_QTY[sym] // 2, 1)

        want_short = sig_upper == "RSI>80"
        want_long  = sig_upper == "RSI<20"

        if pos == 0:                                # открытие ½
            side = "sell" if want_short else "buy"
            res  = await execute_market_order(sym, side, half)
            if res:
                current_positions[sym] = -half if want_short else half
                entry_prices[sym]      = res["price"]
                await send_telegram_log(
                    f"🚀 {sig_upper}: open {'SHORT' if want_short else 'LONG'} "
                    f"{half} @ {res['price']:.2f}")
            return {"status": "rsi80_20_open"}

        if (want_short and pos > 0) or (want_long and pos < 0):   # flip
            side = "sell" if pos > 0 else "buy"
            qty  = abs(pos) + half
            res  = await execute_market_order(sym, side, qty)
            if res:
                current_positions[sym] = -half if side == "sell" else half
                entry_prices[sym]      = res["price"]
                await send_telegram_log(f"🔄 {sig_upper}: flip {sym}")
            return {"status": "rsi80_20_flip"}

        return {"status": "noop_rsi80_20"}

    # ───────────────────────── RSI >70 / <30 ────────────────────────────────
    if sig_upper in ("RSI>70", "RSI<30"):
        if now < tp_block_until.get(sym, 0):
            await send_telegram_log("⏳ RSI blocked after TP")
            return {"status": "rsi_blocked_by_tp"}

        key = f"{sym}:{sig_upper}"
        if now - last_rsi_signal.get(key, 0) < RSI_COOLDOWN_SEC:
            return {"status": "rsi_cooldown"}
        last_rsi_signal[key] = now

        pos = (await get_current_positions()).get(sym, 0)
        if pos == 0:
            return {"status": "no_position"}

        close_long  = sig_upper == "RSI>70" and pos > 0
        close_short = sig_upper == "RSI<30" and pos < 0
        if not (close_long or close_short):
            return {"status": "dir_mismatch"}

        side = "sell" if pos > 0 else "buy"
        qty  = abs(pos)                               # закрываем ***всё***
        res  = await execute_market_order(sym, side, qty)
        if res:
            current_positions[sym] = 0
            entry_prices.pop(sym, None)
            await send_telegram_log(
                f"🔔 {sig_upper}: closed ALL {qty} @ {res['price']:.2f}")
        return {"status": "rsi70_30_close"}

    # ───────────────────────── LONG / SHORT ────────────────────────────────
    if sig_upper not in ("LONG", "SHORT"):
        await send_telegram_log(f"⚠️ Unknown action {sig_upper}")
        return {"status": "invalid_action"}

    dir_ = 1 if sig_upper == "LONG" else -1
    side = "buy" if dir_ > 0 else "sell"
    pos  = (await get_current_positions()).get(sym, 0)

    # flip
    if pos * dir_ < 0:
        qty = abs(pos) + START_QTY[sym]
        res = await execute_market_order(sym, side, qty)
        if res:
            current_positions[sym] = dir_ * START_QTY[sym]
            entry_prices[sym]      = res["price"]
            tp_block_until.pop(sym, None)
            await send_telegram_log(f"🟢 flip {sym}")
        return {"status": "flip"}

    # averaging
    if pos * dir_ > 0:
        new = pos + ADD_QTY[sym]
        if abs(new) > MAX_QTY[sym]:
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}")
            return {"status": "limit"}
        res = await execute_market_order(sym, side, ADD_QTY[sym])
        if res:
            current_positions[sym] = new
            await send_telegram_log(f"➕ avg {sym}: {new:+}")
        return {"status": "avg"}

    # open
    if pos == 0:
        res = await execute_market_order(sym, side, START_QTY[sym])
        if res:
            current_positions[sym] = dir_ * START_QTY[sym]
            entry_prices[sym]      = res["price"]
            await send_telegram_log(f"✅ open {sym} {current_positions[sym]:+}")
        return {"status": "open"}

    return {"status": "noop"}


__all__ = ["total_profit", "initial_balance"]
