# trading.py
# ─────────────────────────────────────────────────────────────────────────────
#   *** 2025‑07‑15  patch‑6 ***
#
#   Изменено только поведение сигналов:
#     • TPL  / TPS
#     • RSI30 / RSI20 / RSI70 / RSI80
#
#   Все ограничения cooldown, retry‑clearing, лимиты MAX_QTY и логика
#   LONG / SHORT / averaging оставлены без изменений.
# ─────────────────────────────────────────────────────────────────────────────

import asyncio, time
from telegram_logger import send_telegram_log
from config import TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY
from alor   import place_order, get_position_snapshot, get_current_positions

# ──────────── глобальные состояния ──────────────────────────────────────────
current_positions            = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices:      dict[str, float] = {}

last_rsi_signal:   dict[str, float] = {}
last_tp_signal:    dict[str, float] = {}
tp_block_until:    dict[str, float] = {}

RSI_COOLDOWN_SEC  = 60 * 60                       # 1 ч
TP_COOLDOWN_SEC   = {"CNY-9.25": 30 * 60,
                     "NG-7.25" : 15 * 60}
TP_BLOCK_SEC      = {"CNY-9.25": 30 * 60,
                     "NG-7.25" : 10 * 60}

# ───────── util: маркет‑ордер с гарантией исполнения ────────────────────────
async def execute_market_order(sym: str, side: str, qty: int,
                               *, retries: int = 3, delay: int = 300):
    for attempt in range(1, retries + 1):
        res = await place_order({"side": side.upper(),
                                 "qty":  qty,
                                 "instrument": sym,
                                 "symbol":     sym})
        if "error" in res:
            err = str(res["error"])
            if ("ExchangeUndefinedError" in err and "клиринг" in err.lower()) \
               or ("session" in err.lower() and "closed" in err.lower()):
                await send_telegram_log(
                    f"⏳ {sym}: {err.strip() or 'clearing'} retry {attempt}/{retries}")
                await asyncio.sleep(delay)
                continue
            await send_telegram_log(f"❌ order {side}/{sym}/{qty}: {err}")
            return None
        await asyncio.sleep(30)
        snap = await get_position_snapshot(sym)
        return {"price": res.get("price", 0.0),
                "position": snap.get("qty", 0)}
    await send_telegram_log(f"⚠️ {sym}: clearing retries exceeded")
    return None


async def place_and_ensure(sym: str, side: str, qty: int,
                           *, attempts: int = 5, delay: int = 300):
    for attempt in range(1, attempts + 1):
        before = (await get_current_positions()).get(sym, 0)
        res    = await execute_market_order(sym, side, qty)
        if res:
            after = res["position"]
            if abs(after - before) >= qty:
                return res
        await send_telegram_log(
            f"⏳ {sym}: order not filled (try {attempt}/{attempts}); retry "
            f"in {delay//60} min")
        await asyncio.sleep(delay)
    await send_telegram_log(f"⚠️ {sym}: unable to fill after {attempts} tries")
    return None

# ═════════════════════ main entry point ═════════════════════════════════════
async def process_signal(tv_tkr: str, sig: str):
    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Unknown ticker {tv_tkr}")
        return {"error": "unknown_ticker"}

    sym       = TICKER_MAP[tv_tkr]["trade"]
    sig_u     = sig.upper()
    now       = time.time()

    pos       = (await get_current_positions()).get(sym, 0)
    start     = START_QTY[sym]
    half      = max(start // 2, 1)

    # ──────────────────────────── TPL / TPS ────────────────────────────
    if sig_u in ("TPL", "TPS"):
        cd = TP_COOLDOWN_SEC[sym]
        if now - last_tp_signal.get(f"{sym}:{sig_u}", 0) < cd:
            return {"status": "tp_cooldown"}
        last_tp_signal[f"{sym}:{sig_u}"] = now

        if sig_u == "TPL":                         # хотим или усилить SHORT
            side = "sell"
            qty  = abs(pos) + half if pos > 0 else half
        else:                                     # TPS → хотим усилить LONG
            side = "buy"
            qty  = abs(pos) + half if pos < 0 else half

        res = await place_and_ensure(sym, side, qty)
        if res:
            current_positions[sym] = pos - qty if side == "sell" else pos + qty
            if current_positions[sym] == 0:
                entry_prices.pop(sym, None)
            tp_block_until[sym] = now + TP_BLOCK_SEC[sym]
        return {"status": sig_u.lower(), "filled": qty}

    # ─────────────────────────── RSI 30 / 20 ────────────────────────────
    if sig_u == "RSI30":
        if pos > 0:                                # long → докупить ½
            side, qty = ("buy", half)
        else:                                      # short / flat → закрыть short + ½ long
            side, qty = ("buy", abs(pos) + half)
        res = await place_and_ensure(sym, side, qty)
        return {"status": "rsi30", "filled": qty}

    if sig_u == "RSI20":                           # всегда +½ long
        res = await place_and_ensure(sym, "buy", half)
        return {"status": "rsi20", "filled": half}

    # ─────────────────────────── RSI 70 / 80 ────────────────────────────
    if sig_u == "RSI70":
        if pos > 0:                                # long → закрыть полностью
            side, qty = ("sell", abs(pos))
        else:                                      # short / flat → ещё ½ short
            side, qty = ("sell", half)
        res = await place_and_ensure(sym, side, qty)
        return {"status": "rsi70", "filled": qty}

    if sig_u == "RSI80":                           # всегда +½ short
        res = await place_and_ensure(sym, "sell", half)
        return {"status": "rsi80", "filled": half}

    # ───────────────── LONG / SHORT / avg / flip (не трогали) ───────────
    if sig_u not in ("LONG", "SHORT"):
        await send_telegram_log(f"⚠️ Unknown action {sig_u}")
        return {"status": "invalid_action"}

    dir_ = 1 if sig_u == "LONG" else -1
    side = "buy" if dir_ > 0 else "sell"
    pos  = (await get_current_positions()).get(sym, 0)

    # flip
    if pos * dir_ < 0:
        qty = abs(pos) + START_QTY[sym]
        res = await place_and_ensure(sym, side, qty)
        if res:
            current_positions[sym] = dir_ * START_QTY[sym]
            entry_prices[sym]      = res["price"]
            tp_block_until.pop(sym, None)
        return {"status": "flip"}

    # averaging
    if pos * dir_ > 0:
        new = pos + ADD_QTY[sym]
        if abs(new) > MAX_QTY[sym]:
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}")
            return {"status": "limit"}
        res = await place_and_ensure(sym, side, ADD_QTY[sym])
        if res:
            current_positions[sym] = new
        return {"status": "avg"}

    # open
    if pos == 0:
        res = await place_and_ensure(sym, side, START_QTY[sym])
        if res:
            current_positions[sym] = dir_ * START_QTY[sym]
            entry_prices[sym]      = res["price"]
        return {"status": "open"}

    return {"status": "noop"}


__all__ = ["total_profit", "initial_balance"]
