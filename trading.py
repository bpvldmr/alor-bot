# trading.py
# ─────────────────────────────────────────────────────────────────────────────
#   *** 2025-07-14 patch-4  ***
#
#   Изменения:
#   1. patch-3 (14-июля) — TPL/TPS теперь закрывают половину позиции для всех
#      инструментов.
#   2. patch-4 (добавлено сейчас)
#      • Новая функция 𝘱𝘭𝘢𝘤𝘦_𝘢𝘯𝘥_𝘦𝘯𝘴𝘶𝘳𝘦()  ─ проверяет, что заявка действительно
#        исполнилась нужным объёмом; если нет — через 5 мин снова пытается
#        отправить маркет-ордер (до 5 попыток).
#      • Все вызовы execute_market_order() внутри process_signal() заменены на
#        place_and_ensure() – теперь любой сигнал будет «дожиматься» до
#        фактического исполнения или 5 промахов подряд.
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

RSI_COOLDOWN_SEC  = 60 * 60                       # 1 час
TP_COOLDOWN_SEC   = {"CNY-9.25": 30 * 60,
                     "NG-7.25" : 15 * 60}
TP_BLOCK_SEC      = {"CNY-9.25": 30 * 60,
                     "NG-7.25" : 10 * 60}

# ───────── util: маркет-ордер с retry при «клиринге» ────────────────────────
async def execute_market_order(sym: str, side: str, qty: int,
                               *, retries: int = 3, delay: int = 300):
    """
    ► Отправляет маркет-ордер.
    ► Повторяет до `retries` раз, если биржа в клиринге.
    ► Возвращает None при ошибке или словарь {"price": …, "position": …}.
    """
    for attempt in range(1, retries + 1):
        res = await place_order({"side": side.upper(),
                                 "qty":  qty,
                                 "instrument": sym,
                                 "symbol":     sym})
        if "error" in res:
            err = str(res["error"])
            # повторяем только для клиринга / закрытой сессии
            if ("ExchangeUndefinedError" in err and "клиринг" in err.lower()) \
               or ("session" in err.lower() and "closed" in err.lower()):
                await send_telegram_log(
                    f"⏳ {sym}: {err.strip() or 'clearing'} "
                    f"retry {attempt}/{retries}")
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


# ───────── новинка: гарантируем исполнение ─────────────────────────────────
async def place_and_ensure(sym: str, side: str, qty: int,
                           *, attempts: int = 5, delay: int = 300):
    """
    Отправляем маркет-ордер и проверяем, что позиция изменилась минимум на `qty`.
    Если нет — ждём 5 минут и повторяем (до `attempts` раз).
    Возвращает тот же словарь, что execute_market_order(), либо None.
    """
    for attempt in range(1, attempts + 1):
        before = (await get_current_positions()).get(sym, 0)
        res    = await execute_market_order(sym, side, qty)
        if res is not None:
            after = res["position"]
            if abs(after - before) >= qty:
                return res    # успех
        await send_telegram_log(
            f"⏳ {sym}: order not filled "
            f"(attempt {attempt}/{attempts}); retry in {delay//60} min")
        await asyncio.sleep(delay)

    await send_telegram_log(f"⚠️ {sym}: unable to fill order after {attempts} tries")
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
        qty  = max(abs(pos) // 2, 1)               # половина позиции

        res  = await place_and_ensure(sym, side, qty)   # ← НОВЫЙ вызов
        if res:
            current_positions[sym] = pos - qty if side == "sell" else pos + qty
            if current_positions[sym] == 0:
                entry_prices.pop(sym, None)
            await send_telegram_log(
                f"💰 {sig_upper} {sym}: closed {qty} @ {res['price']:.2f}")

            tp_block_until[sym] = now + TP_BLOCK_SEC[sym]   # блок RSI-70/30
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

        # открытие ½
        if pos == 0:
            side = "sell" if want_short else "buy"
            res  = await place_and_ensure(sym, side, half)
            if res:
                current_positions[sym] = -half if want_short else half
                entry_prices[sym]      = res["price"]
                await send_telegram_log(
                    f"🚀 {sig_upper}: open "
                    f"{'SHORT' if want_short else 'LONG'} {half} @ {res['price']:.2f}")
            return {"status": "rsi80_20_open"}

        # flip
        if (want_short and pos > 0) or (want_long and pos < 0):
            side = "sell" if pos > 0 else "buy"
            qty  = abs(pos) + half
            res  = await place_and_ensure(sym, side, qty)
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
        qty  = abs(pos)                               # закрываем всё
        res  = await place_and_ensure(sym, side, qty)
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
        res = await place_and_ensure(sym, side, qty)
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
        res = await place_and_ensure(sym, side, ADD_QTY[sym])
        if res:
            current_positions[sym] = new
            await send_telegram_log(f"➕ avg {sym}: {new:+}")
        return {"status": "avg"}

    # open
    if pos == 0:
        res = await place_and_ensure(sym, side, START_QTY[sym])
        if res:
            current_positions[sym] = dir_ * START_QTY[sym]
            entry_prices[sym]      = res["price"]
            await send_telegram_log(
                f"✅ open {sym} {current_positions[sym]:+}")
        return {"status": "open"}

    return {"status": "noop"}


__all__ = ["total_profit", "initial_balance"]
