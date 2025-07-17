# trading.py
# ─────────────────────────────────────────────────────────────────────────────
#   *** 2025‑07‑17  patch‑12 ***
#
#   Раздельные ограничения:
#     • TP‑cooldown (TPL/TPS) НЕ блокирует RSI.
#     • Каждый RSI‑тип имеет собственный cooldown‑ключ (нет взаимных блоков).
#     • tp_block_until legacy (не используется в расчётах).
#
#   Flip‑&‑half логика для всех сигналов:
#     TPL, TPS, RSI<30, RSI<20, RSI>70, RSI>80  (см. таблицу ниже).
#
#   qty: half = max(START_QTY[sym] // 2, 1)
#
#   ┌─────────┬────────────────────────────────────────────────────────────────┐
#   │ Сигнал  │ Действие                                                      │
#   ├─────────┼────────────────────────────────────────────────────────────────┤
#   │ TPL     │ pos>0 → SELL abs(pos)+half  (flip long→short½)                │
#   │         │ pos≤0 → SELL half            (усилить/откр. short½)           │
#   ├─────────┼────────────────────────────────────────────────────────────────┤
#   │ TPS     │ pos<0 → BUY  abs(pos)+half  (flip short→long½)                │
#   │         │ pos≥0 → BUY  half            (усилить/откр. long½)            │
#   ├─────────┼────────────────────────────────────────────────────────────────┤
#   │ RSI<30  │ pos<0 → BUY  abs(pos)+half  (flip short→long½)                │
#   │         │ иначе BUY half                                                  │
#   ├─────────┼────────────────────────────────────────────────────────────────┤
#   │ RSI<20  │ pos<0 → BUY  abs(pos)+half  (flip short→long½)                │
#   │         │ иначе BUY half                                                  │
#   ├─────────┼────────────────────────────────────────────────────────────────┤
#   │ RSI>70  │ pos>0 → SELL abs(pos)+half  (flip long→short½)                │
#   │         │ иначе SELL half                                                 │
#   ├─────────┼────────────────────────────────────────────────────────────────┤
#   │ RSI>80  │ pos>0 → SELL abs(pos)+half  (flip long→short½)                │
#   │         │ иначе SELL half                                                 │
#   └─────────┴────────────────────────────────────────────────────────────────┘
#
#   LONG / SHORT базовая логика (flip / avg / open) без изменений.
# ─────────────────────────────────────────────────────────────────────────────

import asyncio, time
from telegram_logger import send_telegram_log
from config import TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY
from alor   import place_order, get_position_snapshot, get_current_positions

# ──────────── глобальные состояния ──────────────────────────────────────────
current_positions            = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices:      dict[str, float] = {}

last_rsi_signal:   dict[str, float] = {}   # "SYM:RSI<30" / "SYM:RSI>70" / ...
last_tp_signal:    dict[str, float] = {}   # "SYM:TPL" / "SYM:TPS"

# legacy: ранее блокировали RSI после TP; теперь НЕ используем, но держим для совм.
tp_block_until:    dict[str, float] = {}

RSI_COOLDOWN_SEC  = 60 * 60                       # 1 час (для каждого RSI‑типа отдельно)
TP_COOLDOWN_SEC   = {v["trade"]: 30 * 60 for v in TICKER_MAP.values()}  # TPL/TPS CD

# ───────── util: маркет-ордер с retry при «клиринге» ────────────────────────
async def execute_market_order(sym: str, side: str, qty: int,
                               *, retries: int = 3, delay: int = 300):
    """
    Отправляет маркет-ордер; при клиринге/закрытой сессии повторяет retry раз.
    Возвращает dict(price, position) или None.
    """
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


# ───────── гарантированное исполнение (повтор через 5 мин) ──────────────────
async def place_and_ensure(sym: str, side: str, qty: int,
                           *, attempts: int = 5, delay: int = 300):
    """
    Пытаемся добиться фактического изменения позиции минимум на qty.
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

    await send_telegram_log(f"⚠️ {sym}: unable to fill after {attempts} tries")
    return None


# ───────── helper: локально обновить позицию ────────────────────────────────
def _apply_position_update(sym: str, pos_before: int, side: str, qty: int, fill_price: float):
    """
    Обновляет current_positions / entry_prices после сделок.
    """
    if side == "buy":
        new_pos = pos_before + qty
    else:
        new_pos = pos_before - qty

    current_positions[sym] = new_pos

    if new_pos == 0:
        entry_prices.pop(sym, None)
        return new_pos

    if pos_before == 0 or pos_before * new_pos <= 0:
        entry_prices[sym] = fill_price
    return new_pos


# ───────── нормализация входящего сигнала ------------------------------------
def _normalize_signal(raw: str) -> str:
    """
    Приводим к верхнему регистру, убираем пробелы.
    НИКАКИХ алиасов: принимаются только строки с символами '<' либо '>'.
    Пример: 'rsi<30' -> 'RSI<30'; 'RSI30' останется 'RSI30' (и будет invalid).
    """
    return raw.strip().upper().replace(" ", "")


# ═════════════════════ main entry point ═════════════════════════════════════
async def process_signal(tv_tkr: str, sig: str):
    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Unknown ticker {tv_tkr}")
        return {"error": "Unknown ticker"}

    sym        = TICKER_MAP[tv_tkr]["trade"]       # напр. CNY-9.25 / NG-7.25 / ...
    sig_upper  = _normalize_signal(sig)
    now        = time.time()

    # текущее фактическое положение (живые данные)
    pos        = (await get_current_positions()).get(sym, 0)
    start      = START_QTY[sym]
    half       = max(start // 2, 1)

    # ─────────────────────────────── TP (TPL/TPS) ──────────────────────
    if sig_upper in ("TPL", "TPS"):
        cd = TP_COOLDOWN_SEC.get(sym, 30 * 60)
        if now - last_tp_signal.get(f"{sym}:{sig_upper}", 0) < cd:
            await send_telegram_log(f"⏳ {sig_upper} ignored ({cd//60}m CD)")
            return {"status": "tp_cooldown"}
        last_tp_signal[f"{sym}:{sig_upper}"] = now

        if sig_upper == "TPL":       # long → close all & open ½ short, else add ½ short
            side = "sell"
            qty  = abs(pos) + half if pos > 0 else half
        else:                        # TPS: short → close all & open ½ long, else add ½ long
            side = "buy"
            qty  = abs(pos) + half if pos < 0 else half

        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await send_telegram_log(
                f"💰 {sig_upper} {sym}: {side} {qty} @ {res['price']:.2f}")
        return {"status": sig_upper.lower(), "filled": qty}

    # ───────────────────────────── RSI<30 / RSI>70 ─────────────────────
    if sig_upper in ("RSI<30", "RSI>70"):
        key = f"{sym}:{sig_upper}"
        if now - last_rsi_signal.get(key, 0) < RSI_COOLDOWN_SEC:
            return {"status": "rsi_cooldown"}
        last_rsi_signal[key] = now

        pos = (await get_current_positions()).get(sym, 0)

        if sig_upper == "RSI<30":
            # short → flip в лонг½; иначе +½ лонг
            if pos < 0:
                side, qty = ("buy", abs(pos) + half)
            else:
                side, qty = ("buy", half)
            res = await place_and_ensure(sym, side, qty)
            if res:
                _apply_position_update(sym, pos, side, qty, res["price"])
                await send_telegram_log(f"🔔 RSI<30 {sym}: buy {qty}")
            return {"status": "rsi_lt30"}

        else:  # RSI>70
            # long → flip в шорт½; иначе +½ шорт
            if pos > 0:
                side, qty = ("sell", abs(pos) + half)
            else:
                side, qty = ("sell", half)
            res = await place_and_ensure(sym, side, qty)
            if res:
                _apply_position_update(sym, pos, side, qty, res["price"])
                await send_telegram_log(f"🔔 RSI>70 {sym}: sell {qty}")
            return {"status": "rsi_gt70"}

    # ───────────────────────────── RSI<20 / RSI>80 ─────────────────────
    if sig_upper == "RSI<20":
        # short → flip в лонг½; иначе +½ лонг
        if pos < 0:
            side, qty = ("buy", abs(pos) + half)
        else:
            side, qty = ("buy", half)
        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await send_telegram_log(f"RSI<20 {sym}: buy {qty}")
        return {"status": "rsi_lt20"}

    if sig_upper == "RSI>80":
        # long → flip в шорт½; иначе +½ шорт
        if pos > 0:
            side, qty = ("sell", abs(pos) + half)
        else:
            side, qty = ("sell", half)
        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await send_telegram_log(f"RSI>80 {sym}: sell {qty}")
        return {"status": "rsi_gt80"}

    # ───────────────────────── LONG / SHORT ─────────────────────────────
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
            _apply_position_update(sym, pos, side, qty, res["price"])
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
            _apply_position_update(sym, pos, side, ADD_QTY[sym], res["price"])
            await send_telegram_log(f"➕ avg {sym}: {new:+}")
        return {"status": "avg"}

    # open
    if pos == 0:
        res = await place_and_ensure(sym, side, START_QTY[sym])
        if res:
            _apply_position_update(sym, pos, side, START_QTY[sym], res["price"])
            await send_telegram_log(f"✅ open {sym} {START_QTY[sym]:+}")
        return {"status": "open"}

    return {"status": "noop"}


__all__ = ["total_profit", "initial_balance"]
