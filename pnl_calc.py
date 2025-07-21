# pnl_calc.py
# ─────────────────────────────────────────────────────────────
# 2025‑07‑21  v1.0
#
# • Асинхронно берёт фактическую цену последней сделки по тикеру
#   через /md/v2/Clients/MOEX/{ACCOUNT_ID}/trades
# • Считает PnL и %‑доходность
# • Можно использовать:
#     pnl, pct = calc_pnl(entry, exit, signed_qty)            # если exit известна
#     pnl, pct, exit = await calc_pnl_auto(ticker, entry, qty)  # если exit ещё нет
# ─────────────────────────────────────────────────────────────
import time
from typing import Tuple

import httpx
from auth   import get_access_token
from config import BASE_URL, ACCOUNT_ID, TICKER_MAP
from loguru import logger

# ───────────────────── вспомогательное соответствие символов ────────────────
def _get_alor_symbol(ticker: str) -> str:
    """Преобразует название trade‑тикера в symbol, если они различаются."""
    for info in TICKER_MAP.values():
        if info["trade"] == ticker:
            return info["symbol"]
    return ticker


# ───────────────────── фактическая цена последней сделки ────────────────────
async def get_last_trade_price(ticker: str, *, lookback_sec: int = 60) -> float:
    """
    Возвращает цену самой последней сделки по инструменту `ticker`
    за последние `lookback_sec` секунд.
    Если сделок нет, вернёт 0.0.
    """
    symbol  = _get_alor_symbol(ticker)
    token   = await get_access_token()

    to_ts   = int(time.time() * 1000)
    from_ts = to_ts - lookback_sec * 1000

    url = (
        f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/trades"
        f"?from={from_ts}&to={to_ts}&format=Simple&withCurrencies=false"
    )
    headers = { "Authorization": f"Bearer {token}" }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            trades = resp.json() or []
    except Exception as e:
        logger.error(f"get_last_trade_price: {e}")
        return 0.0

    # берём самую свежую по symbol
    for tr in sorted(trades, key=lambda x: x.get("moment", 0), reverse=True):
        if tr.get("symbol") == symbol:
            return float(tr.get("price", 0.0))
    return 0.0


# ───────────────────────── базовый расчёт PnL ───────────────────────────────
def calc_pnl(entry_price: float, exit_price: float, signed_qty: int) -> Tuple[float, float]:
    """
    • signed_qty > 0 → позиция была LONG, закрылась SELL
    • signed_qty < 0 → позиция была SHORT, закрылась BUY

    Возвращает (pnl, pct).  pnl — в той же валюте, pct — от первоначальных затрат.
    """
    if signed_qty == 0 or entry_price == 0:
        return 0.0, 0.0

    pnl = round((exit_price - entry_price) * signed_qty * -1, 2)
    pct = round((pnl / (entry_price * abs(signed_qty))) * 100, 2)
    return pnl, pct


# ─────────────────── удобная «всё‑в‑одном» обёртка ──────────────────────────
async def calc_pnl_auto(
    ticker: str,
    entry_price: float,
    signed_qty: int,
    *,
    lookback_sec: int = 60
) -> Tuple[float, float, float]:
    """
    • Берёт последнюю цену сделки (/trades) для `ticker`
    • Считает pnl, pct
    • Возвращает (pnl, pct, exit_price)   ← exit_price полезно для логов
    """
    exit_price = await get_last_trade_price(ticker, lookback_sec=lookback_sec)
    pnl, pct   = calc_pnl(entry_price, exit_price, signed_qty)
    return pnl, pct, exit_price
