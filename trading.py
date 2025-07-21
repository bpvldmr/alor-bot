# trading.py
# ─────────────────────────────────────────────────────────────────────────────
#   *** 2025‑07‑21  patch‑19 ***
#
#   ➤ ГЛАВНОЕ: Единый контроль MAX_QTY для ЛЮБОЙ заявки.
#     • helper exceeds_limit(...)
#     • Проверка вставлена во все ветки перед place_and_ensure().
#
#   Остальное — логика сигналов patch‑18 (TPL2/TPS2, усреднение, цена /trades).
# ─────────────────────────────────────────────────────────────────────────────
import asyncio, time
from telegram_logger import send_telegram_log
from config   import TICKER_MAP, START_QTY, ADD_QTY, MAX_QTY
from alor     import place_order, get_position_snapshot, get_current_positions
from balance  import log_balance
from pnl_calc import get_last_trade_price

# ──────────── глобальные состояния ──────────────────────────────────────────
current_positions            = {v["trade"]: 0 for v in TICKER_MAP.values()}
entry_prices:      dict[str, float] = {}

last_tp_signal:    dict[str, float] = {}
last_tp_state:     dict[str, int]   = {}       # 1 = был TPL, -1 = был TPS
last_signal_ts:    dict[str, float] = {}

RSI_COOLDOWN_SEC  = 60 * 60
GEN_COOLDOWN_SEC  = 60 * 60
TP_COOLDOWN_SEC   = {v["trade"]: 30 * 60 for v in TICKER_MAP.values()}

# ───────── helper‑ы ─────────────────────────────────────────────────────────
def exceeds_limit(sym: str, side: str, qty: int, cur_pos: int) -> bool:
    new_pos = cur_pos + qty if side == "buy" else cur_pos - qty
    return abs(new_pos) > MAX_QTY[sym]

def is_repeat(sym: str, sig_upper: str, now: float, cooldown: int) -> bool:
    key  = f"{sym}:{sig_upper}"
    prev = last_signal_ts.get(key, 0)
    if now - prev >= cooldown:
        last_signal_ts[key] = now
        return prev != 0
    return False

def qty_for_signal(sym: str, repeat: bool, base_qty: int) -> int:
    return ADD_QTY[sym] if repeat else base_qty

# ───────── util: маркет‑ордер с фактической ценой ───────────────────────────
async def execute_market_order(sym: str, side: str, qty: int,
                               *, retries: int = 3, delay: int = 300):
    for attempt in range(1, retries + 1):
        resp = await place_order({
            "side": side.upper(), "qty": qty,
            "instrument": sym, "symbol": sym
        })
        if "error" in resp:
            err = str(resp["error"])
            if ("клиринг" in err.lower()) or ("session" in err.lower() and "closed" in err.lower()):
                await send_telegram_log(f"⏳ {sym}: {err.strip() or 'clearing'} retry {attempt}/{retries}")
                await asyncio.sleep(delay); continue
            await send_telegram_log(f"❌ order {side}/{sym}/{qty}: {err}"); return None
        await asyncio.sleep(30)
        snap  = await get_position_snapshot(sym)
        price = await get_last_trade_price(sym) or resp.get("price", 0.0)
        return {"price": price, "position": snap.get("qty", 0)}
    await send_telegram_log(f"⚠️ {sym}: clearing retries exceeded"); return None

async def place_and_ensure(sym: str, side: str, qty: int,
                           *, attempts: int = 5, delay: int = 300):
    for attempt in range(1, attempts + 1):
        before = (await get_current_positions()).get(sym, 0)
        res    = await execute_market_order(sym, side, qty)
        if res and abs(res["position"] - before) >= qty:
            return res
        await send_telegram_log(
            f"⏳ {sym}: order not filled (attempt {attempt}/{attempts}); retry in {delay//60} min")
        await asyncio.sleep(delay)
    await send_telegram_log(f"⚠️ {sym}: unable to fill after {attempts} tries")
    return None

# ───────── helper: локальное обновление ─────────────────────────────────────
def _apply_position_update(sym: str, pos_before: int, side: str,
                           qty: int, fill_price: float):
    new_pos = pos_before + qty if side == "buy" else pos_before - qty
    current_positions[sym] = new_pos
    if new_pos == 0:
        entry_prices.pop(sym, None)
    elif pos_before == 0 or pos_before * new_pos <= 0:
        entry_prices[sym] = fill_price
    return new_pos

def _normalize_signal(raw: str) -> str: return raw.strip().upper().replace(" ", "")

# ═════════════════════ main entry point ═════════════════════════════════════
async def process_signal(tv_tkr: str, sig: str):
    if tv_tkr not in TICKER_MAP:
        await send_telegram_log(f"⚠️ Unknown ticker {tv_tkr}"); return {"error": "Unknown ticker"}

    sym = TICKER_MAP[tv_tkr]["trade"]; sig_upper = _normalize_signal(sig); now = time.time()
    pos = (await get_current_positions()).get(sym, 0); half = max(START_QTY[sym] // 2, 1)

    # ─── 1. TPL / TPS ─────────────────────────────────────────────────
    if sig_upper in ("TPL", "TPS"):
        cd = TP_COOLDOWN_SEC.get(sym, 30*60)
        if now - last_tp_signal.get(f"{sym}:{sig_upper}", 0) < cd:
            await send_telegram_log(f"⏳ {sig_upper} ignored ({cd//60}m CD)"); return {"status":"tp_cooldown"}
        last_tp_signal[f"{sym}:{sig_upper}"] = now
        if sig_upper=="TPL": side="sell"; qty=abs(pos)+half if pos>0 else half; last_tp_state[sym]=1
        else:                side="buy";  qty=abs(pos)+half if pos<0 else half; last_tp_state[sym]=-1
        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}"); return {"status":"limit"}
        res = await place_and_ensure(sym, side, qty)
        if res: _apply_position_update(sym,pos,side,qty,res["price"]); await log_balance(); \
                 await send_telegram_log(f"💰 {sig_upper} {sym}: {side} {qty} @ {res['price']:.2f}")
        return {"status": sig_upper.lower()}

    # ─── 2. TPL2 / TPS2 ───────────────────────────────────────────────
    if sig_upper in ("TPL2","TPS2"):
        st = last_tp_state.get(sym,0)
        if (sig_upper=="TPL2" and st!=1) or (sig_upper=="TPS2" and st!=-1):
            return {"status": f"{sig_upper.lower()}_ignored"}
        side = "sell" if sig_upper=="TPL2" else "buy"; qty = ADD_QTY[sym]
        if exceeds_limit(sym, side, qty, pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}"); return {"status":"limit"}
        res = await place_and_ensure(sym, side, qty)
        if res: _apply_position_update(sym,pos,side,qty,res["price"]); last_tp_state[sym]=0; \
                 await log_balance(); await send_telegram_log(f"➕ {sig_upper} {sym}: {side} {qty} @ {res['price']:.2f}")
        return {"status": sig_upper.lower()}

    # ─── 3. RSI<30 / RSI>70 ───────────────────────────────────────────
    if sig_upper in ("RSI<30","RSI>70"):
        rep = is_repeat(sym,sig_upper,now,RSI_COOLDOWN_SEC)
        if not rep and f"{sym}:{sig_upper}" in last_signal_ts:
            return {"status":"rsi_cooldown"}
        if sig_upper=="RSI<30":
            if pos<0: side,qty=("buy",abs(pos)+half)
            else: side="buy"; qty=qty_for_signal(sym,rep and pos>0,half)
        else:
            if pos>0: side,qty=("sell",abs(pos)+half)
            else: side="sell"; qty=qty_for_signal(sym,rep and pos<0,half)
        if exceeds_limit(sym,side,qty,pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}"); return {"status":"limit"}
        res=await place_and_ensure(sym,side,qty)
        if res:_apply_position_update(sym,pos,side,qty,res["price"]); await log_balance(); \
               await send_telegram_log(f"🔔 {sig_upper} {sym}: {side} {qty}")
        return {"status":sig_upper.lower()}

    # ─── 4. RSI<20 / RSI>80 ───────────────────────────────────────────
    if sig_upper in ("RSI<20","RSI>80"):
        rep = is_repeat(sym,sig_upper,now,GEN_COOLDOWN_SEC)
        if sig_upper=="RSI<20":
            if pos<0: side,qty=("buy",abs(pos)+half)
            else: side="buy"; qty=qty_for_signal(sym,rep and pos>0,half)
        else:
            if pos>0: side,qty=("sell",abs(pos)+half)
            else: side="sell"; qty=qty_for_signal(sym,rep and pos<0,half)
        if exceeds_limit(sym,side,qty,pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}"); return {"status":"limit"}
        res=await place_and_ensure(sym,side,qty)
        if res:_apply_position_update(sym,pos,side,qty,res["price"]); await log_balance(); \
               await send_telegram_log(f"{sig_upper} {sym}: {side} {qty}")
        return {"status":sig_upper.lower()}

    # ─── 5. LONG / SHORT ──────────────────────────────────────────────
    if sig_upper not in ("LONG","SHORT"):
        await send_telegram_log(f"⚠️ Unknown action {sig_upper}"); return {"status":"invalid_action"}
    dir_ = 1 if sig_upper=="LONG" else -1; side="buy" if dir_>0 else "sell"; rep=is_repeat(sym,sig_upper,now,GEN_COOLDOWN_SEC)

    # flip
    if pos*dir_ <0:
        qty = abs(pos)+START_QTY[sym]
        if exceeds_limit(sym,side,qty,pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}"); return {"status":"limit"}
        res=await place_and_ensure(sym,side,qty)
        if res:_apply_position_update(sym,pos,side,qty,res["price"]); await log_balance(); \
               await send_telegram_log(f"🟢 flip {sym}")
        return {"status":"flip"}

    # averaging / repeat
    if pos*dir_ >0:
        qty = qty_for_signal(sym,rep,ADD_QTY[sym]); new = pos+qty if dir_>0 else pos-qty
        if exceeds_limit(sym,side,qty,pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}"); return {"status":"limit"}
        res=await place_and_ensure(sym,side,qty)
        if res:_apply_position_update(sym,pos,side,qty,res["price"]); await log_balance(); \
               await send_telegram_log(f"➕ avg {sym}: {new:+}")
        return {"status":"avg"}

    # open
    if pos==0:
        qty=START_QTY[sym]
        if exceeds_limit(sym,side,qty,pos):
            await send_telegram_log(f"❌ {sym}: max {MAX_QTY[sym]}"); return {"status":"limit"}
        res=await place_and_ensure(sym,side,qty)
        if res:_apply_position_update(sym,pos,side,qty,res["price"]); await log_balance(); \
               await send_telegram_log(f"✅ open {sym} {qty:+}")
        return {"status":"open"}

    return {"status":"noop"}


__all__ = ["process_signal"]
