# trading.py
# ─────────────────────────────────────────────────────────────────────────────
# 2025-07-22  patch-22
#
# • Новое общее правило усреднения для ВСЕХ сигналов:
#   Если сигнал пришёл и позиция уже есть в нужном направлении,
#   то бот делает ЧИСТОЕ УСРЕДНЕНИЕ объёмом ADD_QTY[sym].
#
#   Применено к RSI<30 / RSI>70 / RSI<20 / RSI>80, а также сохраняем
#   логику для TPL2 / TPS2 и LONG/SHORT (там ADD_QTY уже использовался).
#
# • Поведение при отсутствии позиции или при позиции в обратную сторону
#   остаётся прежним: переворот (закрыть всё + открыть START_QTY)
#   или просто открыть START_QTY.
#
# • Блок TPL / TPS из patch-21 (переворот с полным START_QTY) сохранён.
# • Контроль MAX_QTY — без изменений, перед любой заявкой.
# • Cooldown-ы — без изменений, используются helper-функции.
# ─────────────────────────────────────────────────────────────────────────────
import asyncio, time
from telegram_logger import send_telegram_log
from config   import TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY
from alor     import place_order, get_position_snapshot, get_current_positions
from balance  import log_balance
from pnl_calc import get_last_trade_price

# ──────────── глобальные состояния ──────────────────────────────────────────
current_positions              = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices: dict[str, float] = {}

last_tp_signal: dict[str, float] = {}
last_tp_state:  dict[str, int]   = {}   # 1 = был TPL, –1 = был TPS
last_signal_ts:dict[str, float]  = {}

# Базовые кулдауны (по умолчанию для всех инструментов)
RSI_COOLDOWN_SEC = 60 * 60       # 1 час
GEN_COOLDOWN_SEC = 60 * 60       # 1 час

# Индивидуальные кулдауны для RSI<30/RSI>70:
#   • NG-9.25 — 30 минут
#   • CNY-9.25 — 5 часов
RSI30_70_COOLDOWN_SEC = {
    "NG-9.25": 30 * 60,
    "CNY-9.25": 5 * 60 * 60,
}

# Индивидуальный кулдаун для TPL/TPS только для NG-9.25 = 30 минут.
# Для остальных инструментов ниже используем дефолт 60 минут.
TP_COOLDOWN_SEC = {
    "NG-9.25": 30 * 60,
}

# ───────── helper-функции ───────────────────────────────────────────────────
def exceeds_limit(sym: str, side: str, qty: int, cur_pos: int) -> bool:
    new_pos = cur_pos + qty if side == "buy" else cur_pos - qty
    return abs(new_pos) > MAX_QTY[sym]

def update_and_check_cooldown(sym: str, sig: str, now: float, cd: int) -> bool:
    """True — cooldown активен (сигнал надо игнорировать)."""
    key  = f"{sym}:{sig}"
    prev = last_signal_ts.get(key, 0)
    if prev and now - prev < cd:
        return True
    last_signal_ts[key] = now
    return False

def desired_direction(sig_upper: str) -> int:
    """
    Возвращает направление, которого добиваемся сигналом:
    +1 → хотим ЛОНГ; -1 → ШОРТ; 0 → не используется (например, для TPL/TPS2 логика специфична).
    """
    if sig_upper in ("RSI<30", "RSI<20", "TPS", "TPS2", "LONG"):
        return +1
    if sig_upper in ("RSI>70", "RSI>80", "TPL", "TPL2", "SHORT"):
        return -1
    return 0

# ───────── биржевые утилы ───────────────────────────────────────────────────
async def execute_market_order(sym: str, side: str, qty: int,
                               *, retries: int = 3, delay: int = 300):
    """Отправка маркет-ордера + фактическая цена из /trades."""
    for attempt in range(1, retries + 1):
        resp = await place_order({"side": side.upper(),
                                  "qty":  qty,
                                  "instrument": sym,
                                  "symbol": sym})
        if "error" in resp:
            err = str(resp["error"])
            if "клиринг" in err.lower() or ("session" in err.lower() and "closed" in err.lower()):
                await send_telegram_log(f"⏳ {sym}: {err.strip() or 'clearing'} retry {attempt}/{retries}")
                await asyncio.sleep(delay)
                continue
            await send_telegram_log(f"❌ order {side}/{sym}/{qty}: {err}")
            return None
        await asyncio.sleep(30)
        snap  = await get_position_snapshot(sym)
        price = await get_last_trade_price(sym) or resp.get("price", 0.0)
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
        await send_telegram_log(f"⏳ {sym}: order not filled ({attempt}/{attempts}); retry {delay//60}m")
        await asyncio.sleep(delay)
    await send_telegram_log(f"⚠️ {sym}: unable to fill after {attempts} tries")
    return None

def _apply_position_update(sym: str, pos_before: int, side: str,
                           qty: int, fill_price: float):
    new_pos = pos_before + qty if side == "buy" else pos_before - qty
    current_positions[sym] = new_pos
    if new_pos == 0:
        entry_prices.pop(sym, None)
    elif pos_before == 0 or pos_before * new_pos <= 0:
        entry_prices[sym] = fill_price
    return new_pos

def _normalize_signal(raw: str) -> str:
    return raw.strip().upper().replace(" ", "")

# ═════════════════════ main entry point ═════════════════════════════════════
async def process_signal(tv_tkr: str, sig: str):
    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Unknown ticker {tv_tkr}")
        return {"error": "Unknown ticker"}

    sym       = TICKER_MAP[tv_tkr]["trade"]
    sig_upper = _normalize_signal(sig)
    now       = time.time()

    pos  = (await get_current_positions()).get(sym, 0)

        # ──────────────────────────── TPL / TPS ──────────────────────────
    if sig_upper in ("TPL", "TPS"):
        # кулдаун: NG-9.25 = 30м; остальные = 60м
        cd = TP_COOLDOWN_SEC.get(sym, 60*60)
        if now - last_tp_signal.get(f"{sym}:{sig_upper}", 0) < cd:
            await send_telegram_log(f"⏳ {sig_upper} ignored ({cd//60}m CD)")
            return {"status": "tp_cooldown"}
        last_tp_signal[f"{sym}:{sig_upper}"] = now

        # цель направления: TPL → шорт (-1), TPS → лонг (+1)
        want_dir = -1 if sig_upper == "TPL" else +1
        side     = "sell" if want_dir < 0 else "buy"

        if pos == 0:
            qty = START_QTY[sym]
        elif pos * want_dir < 0:
            qty = abs(pos) + START_QTY[sym]   # flip
        else:
            qty = ADD_QTY[sym]                # averaging (was START_QTY before)

        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}")
            return {"status": "limit"}

        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            # флаг последнего TP-состояния (используется для TPL2/TPS2)
            last_tp_state[sym] = 1 if sig_upper == "TPL" else -1
            await log_balance()
            await send_telegram_log(f"💰 {sig_upper} {sym}: {side} {qty} @ {res['price']:.2f}")
        return {"status": sig_upper.lower()}

    # ─────────────── TPL2 / TPS2 — усреднение ТОЛЬКО после TPL / TPS ─────────
    if sig_upper in ("TPL2", "TPS2"):
        state = last_tp_state.get(sym, 0)
        # TPL2 разрешён только если до этого был TPL (state == 1)
        # TPS2 разрешён только если до этого был TPS (state == -1)
        if (sig_upper == "TPL2" and state != 1) or (sig_upper == "TPS2" and state != -1):
            await send_telegram_log(
                f"⏭️ {sig_upper} проигнорирован: не было {'TPL' if sig_upper == 'TPL2' else 'TPS'}"
            )
            return {"status": f"{sig_upper.lower()}_ignored"}

        side = "sell" if sig_upper == "TPL2" else "buy"
        qty  = ADD_QTY[sym]

        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}")
            return {"status": "limit"}

        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            last_tp_state[sym] = 0  # сбрасываем флаг
            await log_balance()
            await send_telegram_log(f"➕ {sig_upper} {sym}: {side} {qty} @ {res['price']:.2f}")
        return {"status": sig_upper.lower()}

    # ───────────────────────── RSI<30 / RSI>70 ───────────────────────
    if sig_upper in ("RSI<30", "RSI>70"):
        # NG-9.25 — 30 минут; CNY-9.25 — 5 часов; остальные — 1 час (по умолчанию)
        cd_rsi = RSI30_70_COOLDOWN_SEC.get(sym, RSI_COOLDOWN_SEC)
        if update_and_check_cooldown(sym, sig_upper, now, cd_rsi):
            return {"status": "rsi_cooldown"}

        want_dir = desired_direction(sig_upper)  # +1 или -1
        same_dir = (pos * want_dir) > 0

        if same_dir:
            # уже в нужном направлении → УСРЕДНЕНИЕ ADD_QTY
            side = "buy" if want_dir > 0 else "sell"
            qty  = ADD_QTY[sym]
        else:
            # позиция отсутствует или она противоположная → переворот
            side = "buy" if want_dir > 0 else "sell"
            qty  = abs(pos) + START_QTY[sym] if pos != 0 else START_QTY[sym]

        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}")
            return {"status": "limit"}

        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"🔔 {sig_upper} {sym}: {side} {qty}")
        return {"status": sig_upper.lower()}

    # ───────────────────────── RSI<20 / RSI>80 ───────────────────────
    if sig_upper in ("RSI<20", "RSI>80"):
        if update_and_check_cooldown(sym, sig_upper, now, GEN_COOLDOWN_SEC):
            return {"status": "rsi_cooldown"}

        want_dir = desired_direction(sig_upper)
        same_dir = (pos * want_dir) > 0

        if same_dir:
            side = "buy" if want_dir > 0 else "sell"
            qty  = ADD_QTY[sym]
        else:
            side = "buy" if want_dir > 0 else "sell"
            qty  = abs(pos) + START_QTY[sym] if pos != 0 else START_QTY[sym]

        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}")
            return {"status": "limit"}

        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"{sig_upper} {sym}: {side} {qty}")
        return {"status": sig_upper.lower()}

    # ───────────────────────── LONG / SHORT ──────────────────────────
    if sig_upper not in ("LONG", "SHORT"):
        await send_telegram_log(f"⚠️ Unknown action {sig_upper}")
        return {"status":"invalid_action"}

    dir_ = 1 if sig_upper == "LONG" else -1
    side = "buy" if dir_ > 0 else "sell"

    # flip
    if pos * dir_ < 0:
        qty = abs(pos) + START_QTY[sym]
        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}")
            return {"status":"limit"}
        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"🟢 flip {sym}")
        return {"status":"flip"}

    # averaging / repeat (ADD_QTY) — как и раньше
    if pos * dir_ > 0 and not update_and_check_cooldown(sym, sig_upper, now, GEN_COOLDOWN_SEC):
        qty = ADD_QTY[sym]
        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}")
            return {"status":"limit"}
        res = await place_and_ensure(sym, side, qty)
        if res:
            new_pos = pos + qty if dir_ > 0 else pos - qty
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"➕ avg {sym}: {new_pos:+}")
        return {"status":"avg"}

    # open
    if pos == 0:
        qty = START_QTY[sym]
        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}")
            return {"status":"limit"}
        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"✅ open {sym} {qty:+}")
        return {"status":"open"}

    return {"status":"noop"}


__all__ = ["process_signal"]
