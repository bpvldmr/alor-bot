# trading.py
# ─────────────────────────────────────────────────────────────────────────────
# ВАЖНО: Остальная логика НЕ тронута:
#   ─ TPL/TPS: первый сигнал → flip + START_QTY; повторный подряд → усреднение ADD_QTY.
#   ─ RSI 30/70: если уже в направлении (или после TP в ту же сторону) → ADD_QTY,
#                 иначе flip/START_QTY.
#   ─ RSI 20/80, LONG/SHORT — как было.
#   ─ TPL2/TPS2 — игнорируются как «unknown action».
# ─────────────────────────────────────────────────────────────────────────────
import asyncio, time
from telegram_logger import send_telegram_log
from config   import TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY
from alor     import place_order, get_position_snapshot, get_current_positions
from balance  import log_balance
from pnl_calc import get_last_trade_price

# ──────────── глобальные состояния ──────────────────────────────────────────
current_positions = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices: dict[str, float] = {}

last_tp_signal: dict[str, float] = {}   # время TPL / TPS
last_tp_state:  dict[str, int]   = {}   # 1 = последний был TPL, –1 = последний был TPS
last_signal_ts: dict[str, float] = {}   # метки времени прочих сигналов (для cooldown-ов)

# ───────── cooldown-ы ───────────────────────────────────────────────────────
RSI_COOLDOWN_SEC_DEFAULT = 60 * 60   # 60 минут по умолчанию для RSI<30/RSI>70
GEN_COOLDOWN_SEC         = 60 * 60   # для RSI<20/80 и LONG/SHORT
TP_COOLDOWN_SEC          = {v["trade"]: 30 * 60 for v in TICKER_MAP.values()}

# Индивидуальные RSI<30/RSI>70 кулдауны (оставлено как есть)
RSI_CD_MAP = {
    "CNY9.26": 5 * 60 * 60,   # 5 часов
    "NG-8.25": 90 * 60        # 90 минут
}
get_rsi_cooldown = lambda sym: RSI_CD_MAP.get(sym, RSI_COOLDOWN_SEC_DEFAULT)

# ───────── utils / helpers ──────────────────────────────────────────────────
def _normalize_signal(raw: str) -> str:
    return raw.strip().upper().replace(" ", "")

def _apply_position_update(sym: str, pos_before: int, side: str,
                           qty: int, fill_price: float) -> int:
    new_pos = pos_before + qty if side == "buy" else pos_before - qty
    current_positions[sym] = new_pos
    if new_pos == 0:
        entry_prices.pop(sym, None)
    elif pos_before == 0 or pos_before * new_pos <= 0:
        entry_prices[sym] = fill_price
    return new_pos

def cap_qty_to_max(sym: str, side: str, desired_qty: int, cur_pos: int) -> int:
    """
    Режем желаемый объём так, чтобы |new_pos| <= MAX_QTY[sym].
    Для buy:  new_pos = cur_pos + q  → q <= MAX - cur_pos
    Для sell: new_pos = cur_pos - q  → q <= MAX + cur_pos
    """
    max_q = MAX_QTY[sym]
    cap = (max_q - cur_pos) if side == "buy" else (max_q + cur_pos)
    if cap < 0:
        cap = 0
    allowed = desired_qty if desired_qty <= cap else cap
    return int(max(0, allowed))

# ───────── биржевые I/O ─────────────────────────────────────────────────────
async def execute_market_order(sym: str, side: str, qty: int,
                               *, retries: int = 3, delay: int = 300):
    """Создаём маркет-ордер, ждём фактическую цену из /trades и снапшот позиции."""
    for attempt in range(1, retries + 1):
        r = await place_order({
            "side": side.upper(),
            "qty":  qty,
            "instrument": sym,
            "symbol":     sym
        })
        if "error" in r:
            err = str(r["error"])
            if "клиринг" in err.lower() or ("session" in err.lower() and "closed" in err.lower()):
                await send_telegram_log(f"⏳ {sym}: {err.strip() or 'clearing'} retry {attempt}/{retries}")
                await asyncio.sleep(delay)
                continue
            await send_telegram_log(f"❌ order {side}/{sym}/{qty}: {err}")
            return None

        # ждём, чтобы сделка попала в историю
        await asyncio.sleep(30)

        snap  = await get_position_snapshot(sym)
        price = await get_last_trade_price(sym) or r.get("price", 0.0)
        return {"price": price, "position": snap.get("qty", 0)}

    await send_telegram_log(f"⚠️ {sym}: clearing retries exceeded")
    return None

async def place_and_ensure(sym: str, side: str, qty: int,
                           *, attempts: int = 5, delay: int = 300):
    """Добиваемся фактического изменения позиции минимум на qty."""
    for attempt in range(1, attempts + 1):
        before = (await get_current_positions()).get(sym, 0)
        res    = await execute_market_order(sym, side, qty)
        if res and abs(res["position"] - before) >= qty:
            return res
        await send_telegram_log(
            f"⏳ {sym}: order not filled ({attempt}/{attempts}); retry {delay//60}m")
        await asyncio.sleep(delay)
    await send_telegram_log(f"⚠️ {sym}: unable to fill after {attempts} tries")
    return None

async def place_with_limit(sym: str, side: str, desired_qty: int):
    """
    ЕДИНАЯ ТОЧКА ОТПРАВКИ ЗАЯВКИ С УЧЁТОМ MAX_QTY.
    • перечитываем актуальную позицию
    • режем объём до доступного
    • если стало 0 — лог и выход
    • ставим заявку, обновляем локальный стейт и баланс
    • возвращаем {"price": ..., "qty": allowed} либо None
    """
    pos_live = (await get_current_positions()).get(sym, 0)
    allowed  = cap_qty_to_max(sym, side, desired_qty, pos_live)
    if allowed < desired_qty:
        await send_telegram_log(
            f"✂️ {sym}: cap {desired_qty}→{allowed} due to MAX {MAX_QTY[sym]} (pos {pos_live:+})"
        )
    if allowed == 0:
        await send_telegram_log(f"🚫 {sym}: at MAX {MAX_QTY[sym]} (pos {pos_live:+}), skip")
        return None

    res = await place_and_ensure(sym, side, allowed)
    if not res:
        return None

    _apply_position_update(sym, pos_live, side, allowed, res["price"])
    await log_balance()
    return {"price": res["price"], "qty": allowed}

# ═════════════════════ main entry point ═════════════════════════════════════
async def process_signal(tv_tkr: str, sig: str):
    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Unknown ticker {tv_tkr}")
        return {"error": "Unknown ticker"}

    sym       = TICKER_MAP[tv_tkr]["trade"]
    sig_upper = _normalize_signal(sig)
    now       = time.time()

    # текущее состояние и актуальные лимиты из конфига
    pos       = (await get_current_positions()).get(sym, 0)
    start_q   = START_QTY[sym]
    add_q     = ADD_QTY[sym]
    max_q     = MAX_QTY[sym]

    # Диагностика, чтобы отследить кейсы типа «почему 1 контракт»
    await send_telegram_log(
        f"⚙️ CFG {sym}: start={start_q} add={add_q} max={max_q} pos={pos:+} | signal={sig_upper}"
    )

    # ──────────────────────────── TPL / TPS ──────────────────────────
    if sig_upper in ("TPL", "TPS"):
        cd = TP_COOLDOWN_SEC.get(sym, 30 * 60)
        if now - last_tp_signal.get(f"{sym}:{sig_upper}", 0) < cd:
            await send_telegram_log(f"⏳ {sig_upper} ignored ({cd//60}m CD)")
            return {"status": "tp_cooldown"}
        last_tp_signal[f"{sym}:{sig_upper}"] = now

        # Повторный подряд TPL/TPS → усреднение ADD_QTY
        if sig_upper == "TPL" and last_tp_state.get(sym) == 1:
            side, qty = "sell", add_q
        elif sig_upper == "TPS" and last_tp_state.get(sym) == -1:
            side, qty = "buy",  add_q
        else:
            # Первый TPL/TPS → переворот + START_QTY
            if sig_upper == "TPL":
                side = "sell"
                qty  = (abs(pos) + start_q) if pos > 0 else start_q
                last_tp_state[sym] = 1
            else:
                side = "buy"
                qty  = (abs(pos) + start_q) if pos < 0 else start_q
                last_tp_state[sym] = -1

        res = await place_with_limit(sym, side, qty)
        if res:
            await send_telegram_log(
                f"💰 {sig_upper} {sym}: {side} {res['qty']} @ {res['price']:.2f}"
            )
            return {"status": sig_upper.lower(), "filled": res["qty"]}
        return {"status": "order_failed"}

    # ───────────────────────── RSI<30 / RSI>70 ───────────────────────
    if sig_upper in ("RSI<30", "RSI>70"):
        # Индивидуальный cooldown
        if update_and_check_cooldown(sym, sig_upper, now, get_rsi_cooldown(sym)):
            return {"status": "rsi_cooldown"}

        # Направление сигнала: <30 → long, >70 → short
        want_dir = 1 if sig_upper == "RSI<30" else -1
        side     = "buy" if want_dir > 0 else "sell"

        # Если до этого был TP и позиция уже в нужную сторону — только усреднение
        if last_tp_state.get(sym) == want_dir and pos * want_dir > 0:
            qty = add_q
        else:
            # иначе стандарт: если противоположная позиция → переворот,
            # если flat → открыть START_QTY, если уже по ходу → усреднение
            if pos == 0:
                qty = start_q
            elif pos * want_dir < 0:
                qty = abs(pos) + start_q
            else:
                qty = add_q

        res = await place_with_limit(sym, side, qty)
        if res:
            await send_telegram_log(f"🔔 {sig_upper} {sym}: {side} {res['qty']}")
            return {"status": sig_upper.lower(), "filled": res["qty"]}
        return {"status": "order_failed"}

    # ───────────────────────── RSI<20 / RSI>80 ───────────────────────
    if sig_upper in ("RSI<20", "RSI>80"):
        if update_and_check_cooldown(sym, sig_upper, now, GEN_COOLDOWN_SEC):
            return {"status": "rsi_cooldown"}

        want_dir = 1 if sig_upper == "RSI<20" else -1
        side     = "buy" if want_dir > 0 else "sell"

        # Стандартная логика: усреднять, если уже в ту же сторону; иначе переворот/открытие
        if pos == 0:
            qty = start_q
        elif pos * want_dir > 0:
            qty = add_q
        else:
            qty = abs(pos) + start_q

        res = await place_with_limit(sym, side, qty)
        if res:
            await send_telegram_log(f"{sig_upper} {sym}: {side} {res['qty']}")
            return {"status": sig_upper.lower(), "filled": res["qty"]}
        return {"status": "order_failed"}

    # ───────────────────────── LONG / SHORT (как было) ───────────────
    if sig_upper not in ("LONG", "SHORT"):
        # TPL2/TPS2 и прочее — игнор/неизвестное действие
        await send_telegram_log(f"⚠️ Unknown action {sig_upper}")
        return {"status": "invalid_action"}

    dir_ = 1 if sig_upper == "LONG" else -1
    side = "buy" if dir_ > 0 else "sell"

    # flip
    if pos * dir_ < 0:
        qty = abs(pos) + start_q
        res = await place_with_limit(sym, side, qty)
        if res:
            await send_telegram_log(f"🟢 flip {sym} {res['qty']:+}")
            return {"status": "flip", "filled": res["qty"]}
        return {"status": "order_failed"}

    # averaging / repeat (по cooldown-у)
    if pos * dir_ > 0 and not update_and_check_cooldown(sym, sig_upper, now, GEN_COOLDOWN_SEC):
        qty = add_q
        res = await place_with_limit(sym, side, qty)
        if res:
            new_pos = (await get_current_positions()).get(sym, 0)
            await send_telegram_log(f"➕ avg {sym}: {new_pos:+}")
            return {"status": "avg", "filled": res["qty"]}
        return {"status": "order_failed"}

    # open
    if pos == 0:
        qty = start_q
        res = await place_with_limit(sym, side, qty)
        if res:
            await send_telegram_log(f"✅ open {sym} {res['qty']:+}")
            return {"status": "open", "filled": res["qty"]}
        return {"status": "order_failed"}

    return {"status": "noop"}


__all__ = ["process_signal"]
