# trading.py
# ─────────────────────────────────────────────────────────────────────────────
# 2025-08-06  patch-24
#
# • НОВОЕ: если TPL или TPS повторяется подряд
#   (определяется по last_tp_state: 1 == последний был TPL, −1 == TPS),
#   бот не делает переворот, а лишь усредняет позицию объёмом ADD_QTY.
#
#   ─ первый TPL/TPS → как раньше: close-&-reverse (abs(pos)+START_QTY)
#   ─ повторный      → чистое усреднение ADD_QTY
#
# • Остальное (индивидуальные RSI-cooldown-ы, MAX_QTY-контроль,
#   flip/avg/open, I/O c Alor и отправка отчётов) оставлено без изменений.
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
last_tp_state:  dict[str, int]   = {}   # 1 = был TPL, –1 = был TPS
last_signal_ts:dict[str, float]  = {}   # другие сигналы

# ───────── cooldown-ы ───────────────────────────────────────────────────────
RSI_COOLDOWN_SEC_DEFAULT = 60 * 60             # 60 мин по умолчанию
GEN_COOLDOWN_SEC         = 60 * 60
TP_COOLDOWN_SEC          = {v["trade"]: 30*60 for v in TICKER_MAP.values()}

RSI_CD_MAP = {           # индивидуально для RSI<30 / RSI>70
    "CNY9.26": 5 * 60 * 60,   # 5 часов
    "NG-8.25": 90 * 60        # 90 минут
}
get_rsi_cooldown = lambda sym: RSI_CD_MAP.get(sym, RSI_COOLDOWN_SEC_DEFAULT)

# ───────── helper-ы ─────────────────────────────────────────────────────────
def exceeds_limit(sym, side, qty, cur_pos):
    new = cur_pos + qty if side == "buy" else cur_pos - qty
    return abs(new) > MAX_QTY[sym]

def update_and_check_cooldown(sym, sig, now, cd):
    key = f"{sym}:{sig}"; prev = last_signal_ts.get(key, 0)
    if prev and now - prev < cd:          # ещё не прошло
        return True
    last_signal_ts[key] = now
    return False

def desired_direction(sig):
    if sig in ("RSI<30", "RSI<20", "TPS", "TPS2", "LONG"):
        return 1
    if sig in ("RSI>70", "RSI>80", "TPL", "TPL2", "SHORT"):
        return -1
    return 0


# ───────── low-level I/O ────────────────────────────────────────────────────
async def execute_market_order(sym, side, qty, *, retries=3, delay=300):
    for attempt in range(1, retries+1):
        r = await place_order({"side": side.upper(), "qty": qty,
                               "instrument": sym, "symbol": sym})
        if "error" in r:
            err = str(r["error"])
            if "клиринг" in err.lower() or ("session" in err.lower() and "closed" in err.lower()):
                await send_telegram_log(f"⏳ {sym}: {err.strip() or 'clearing'} retry {attempt}/{retries}")
                await asyncio.sleep(delay); continue
            await send_telegram_log(f"❌ order {side}/{sym}/{qty}: {err}")
            return None
        await asyncio.sleep(30)                             # ждём /trades
        snap  = await get_position_snapshot(sym)
        price = await get_last_trade_price(sym) or r.get("price", 0.0)
        return {"price": price, "position": snap.get("qty", 0)}
    await send_telegram_log(f"⚠️ {sym}: clearing retries exceeded")
    return None


async def place_and_ensure(sym, side, qty, *, attempts=5, delay=300):
    for attempt in range(1, attempts+1):
        before = (await get_current_positions()).get(sym, 0)
        res    = await execute_market_order(sym, side, qty)
        if res and abs(res["position"] - before) >= qty:
            return res
        await send_telegram_log(f"⏳ {sym}: order not filled ({attempt}/{attempts}); retry {delay//60}m")
        await asyncio.sleep(delay)
    await send_telegram_log(f"⚠️ {sym}: unable to fill after {attempts} tries")
    return None


def _apply_position_update(sym, pos_before, side, qty, price):
    new_pos = pos_before + qty if side == "buy" else pos_before - qty
    current_positions[sym] = new_pos
    if new_pos == 0:
        entry_prices.pop(sym, None)
    elif pos_before == 0 or pos_before * new_pos <= 0:
        entry_prices[sym] = price
    return new_pos


_norm = lambda s: s.strip().upper().replace(" ", "")


# ═════════════════════ main entry point ═════════════════════════════════════
async def process_signal(tv_tkr: str, sig: str):
    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Unknown ticker {tv_tkr}")
        return {"error": "Unknown ticker"}

    sym  = TICKER_MAP[tv_tkr]["trade"]; sig_upper = _norm(sig); now = time.time()
    pos  = (await get_current_positions()).get(sym, 0)

    # ──────────────────────────── TPL / TPS ──────────────────────────
    if sig_upper in ("TPL", "TPS"):
        cd = TP_COOLDOWN_SEC.get(sym, 30*60)
        if now - last_tp_signal.get(f"{sym}:{sig_upper}", 0) < cd:
            await send_telegram_log(f"⏳ {sig_upper} ignored ({cd//60}m CD)")
            return {"status": "tp_cooldown"}
        last_tp_signal[f"{sym}:{sig_upper}"] = now

        # ▸  ПОВТОРНЫЙ TPL / TPS → усреднение
        if sig_upper == "TPL" and last_tp_state.get(sym) == 1:
            side, qty = "sell", ADD_QTY[sym]
        elif sig_upper == "TPS" and last_tp_state.get(sym) == -1:
            side, qty = "buy",  ADD_QTY[sym]
        else:                               # первый TPL / TPS → переворот
            if sig_upper == "TPL":
                side = "sell"
                qty  = abs(pos) + START_QTY[sym] if pos > 0 else START_QTY[sym]
                last_tp_state[sym] = 1
            else:
                side = "buy"
                qty  = abs(pos) + START_QTY[sym] if pos < 0 else START_QTY[sym]
                last_tp_state[sym] = -1

        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}")
            return {"status": "limit"}

        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"💰 {sig_upper} {sym}: {side} {qty} @ {res['price']:.2f}")
        return {"status": sig_upper.lower()}

    # ───────────────────────── RSI<30 / RSI>70 ───────────────────────
    if sig_upper in ("RSI<30", "RSI>70"):
        if update_and_check_cooldown(sym, sig_upper, now, get_rsi_cooldown(sym)):
            return {"status": "rsi_cooldown"}
        want_dir = 1 if sig_upper == "RSI<30" else -1
        side = "buy" if want_dir > 0 else "sell"
        qty  = ADD_QTY[sym] if pos * want_dir > 0 else (abs(pos) + START_QTY[sym] if pos else START_QTY[sym])
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
        want_dir = 1 if sig_upper == "RSI<20" else -1
        side = "buy" if want_dir > 0 else "sell"
        qty  = ADD_QTY[sym] if pos * want_dir > 0 else (abs(pos) + START_QTY[sym] if pos else START_QTY[sym])
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
        return {"status": "invalid_action"}

    dir_ = 1 if sig_upper == "LONG" else -1
    side = "buy" if dir_ > 0 else "sell"

    # flip
    if pos * dir_ < 0:
        qty = abs(pos) + START_QTY[sym]
        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}")
            return {"status": "limit"}
        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"🟢 flip {sym}")
        return {"status": "flip"}

    # averaging / repeat
    if pos * dir_ > 0 and not update_and_check_cooldown(sym, sig_upper, now, GEN_COOLDOWN_SEC):
        qty = ADD_QTY[sym]
        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}")
            return {"status": "limit"}
        res = await place_and_ensure(sym, side, qty)
        if res:
            new_pos = pos + qty if dir_ > 0 else pos - qty
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"➕ avg {sym}: {new_pos:+}")
        return {"status": "avg"}

    # open
    if pos == 0:
        qty = START_QTY[sym]
        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}")
            return {"status": "limit"}
        res = await place_and_ensure(sym, side, qty)
        if res:
            _apply_position_update(sym, pos, side, qty, res["price"])
            await log_balance()
            await send_telegram_log(f"✅ open {sym} {qty:+}")
        return {"status": "open"}

    return {"status": "noop"}


__all__ = ["process_signal"]
