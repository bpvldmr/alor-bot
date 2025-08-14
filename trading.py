# trading.py
# ─────────────────────────────────────────────────────────────────────────────
# 2025-08-14  patch-27
#
# • TPL/TPS:
#     ─ первый сигнал всегда flip + START_QTY
#     ─ повторный подряд (тот же тип) → чистое усреднение ADD_QTY
#
# • RSI 30/70:
#     ─ если пришёл после TPL/TPS и позиция уже в направлении сигнала → усреднение ADD_QTY
#     ─ иначе стандартно: flip (если противоположная) или START_QTY (если flat)
#
# • LONG/SHORT: логика не изменялась.
# • TPL2/TPS2: не используются (игнор).
# • MAX_QTY: контроль перед любой отправкой заявки.
# • Диагностика в TG: реальное start/add/max/pos на момент сигнала.
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

# ───────── helpers ──────────────────────────────────────────────────────────
def exceeds_limit(sym: str, side: str, qty: int, cur_pos: int) -> bool:
    new_pos = cur_pos + qty if side == "buy" else cur_pos - qty
    return abs(new_pos) > MAX_QTY[sym]

def update_and_check_cooldown(sym: str, sig: str, now: float, cd: int) -> bool:
    """
    True  → cooldown ещё активен (сигнал игнорируем),
    False → можно исполнять (и одновременно ставим новую метку времени).
    """
    key  = f"{sym}:{sig}"
    prev = last_signal_ts.get(key, 0)
    if prev and now - prev < cd:
        return True
    last_signal_ts[key] = now
    return False

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

# ───────── биржевые утилы ───────────────────────────────────────────────────
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

    # Диагностика в TG — что реально видит код (чтобы ловить кейс «1 контракт»)
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

        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {max_q}")
            return {"status": "limit"}

        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(
                f"💰 {sig_upper} {sym}: {side} {qty} @ {res['price']:.2f}"
            )
        return {"status": sig_upper.lower(), "filled": qty}

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
            # если flat → открыть START_QTY
            if pos == 0:
                qty = start_q
            elif pos * want_dir < 0:
                qty = abs(pos) + start_q
            else:
                # уже в нужном направлении (без связи с TP) — тоже усредняем
                qty = add_q

        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {max_q}")
            return {"status": "limit"}

        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"🔔 {sig_upper} {sym}: {side} {qty}")
        return {"status": sig_upper.lower(), "filled": qty}

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

        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {max_q}")
            return {"status": "limit"}

        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"{sig_upper} {sym}: {side} {qty}")
        return {"status": sig_upper.lower(), "filled": qty}

    # ───────────────────────── LONG / SHORT (как было) ───────────────
    if sig_upper not in ("LONG", "SHORT"):
        # TPL2/TPS2 и прочее — не используем
        await send_telegram_log(f"⚠️ Unknown action {sig_upper}")
        return {"status": "invalid_action"}

    dir_ = 1 if sig_upper == "LONG" else -1
    side = "buy" if dir_ > 0 else "sell"

    # flip
    if pos * dir_ < 0:
        qty = abs(pos) + start_q
        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {max_q}")
            return {"status": "limit"}
        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"🟢 flip {sym}")
        return {"status": "flip", "filled": qty}

    # averaging / repeat (по cooldown-у)
    if pos * dir_ > 0 and not update_and_check_cooldown(sym, sig_upper, now, GEN_COOLDOWN_SEC):
        qty = add_q
        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {max_q}")
            return {"status": "limit"}
        res = await place_and_ensure(sym, side, qty)
        if res:
            new_pos = pos + qty if dir_ > 0 else pos - qty
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"➕ avg {sym}: {new_pos:+}")
        return {"status": "avg", "filled": qty}

    # open
    if pos == 0:
        qty = start_q
        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {max_q}")
            return {"status": "limit"}
        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"✅ open {sym} {qty:+}")
        return {"status": "open", "filled": qty}

    return {"status": "noop"}


__all__ = ["process_signal"]
