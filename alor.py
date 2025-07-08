import uuid
import httpx
from config import BASE_URL, ACCOUNT_ID, TICKER_MAP
from auth   import get_access_token
from telegram_logger import send_telegram_log
from loguru import logger

# ───────────────────────── вспомогательные функции ──────────────────────────
def get_alor_symbol(ticker: str) -> str:
    """
    Принимает trade-строку (а в нашем случае это уже биржевой символ)
    и возвращает symbol для ALOR.  Оставляем цикл по TICKER_MAP
    на случай, если в будущем trade и symbol будут различаться.
    """
    for info in TICKER_MAP.values():
        if info["trade"] == ticker:
            return info["symbol"]
    return ticker            # fallback — уже символ


# ─────────────────────────────── market-ордер ────────────────────────────────
async def place_order(order: dict):
    if not all(k in order for k in ("side", "qty", "instrument")):
        await send_telegram_log("🚫 Неверный формат ордера")
        return {"status": "error", "detail": "Bad order format"}

    token  = await get_access_token()
    url    = f"{BASE_URL}/commandapi/warptrans/TRADE/v2/client/orders/actions/market"
    symbol = get_alor_symbol(order["instrument"])

    headers = {
        "Authorization": f"Bearer {token}",
        "X-REQID":       str(uuid.uuid4()),
        "Accept":        "application/json",
        "Content-Type":  "application/json"
    }

    payload = {
        "side":      order["side"].upper(),
        "quantity":  int(order["qty"]),
        "instrument": {
            "symbol":         symbol,
            "exchange":       "MOEX",
            "instrumentGroup":"RFUD"
        },
        "comment":     "ALGO BOT",
        "user":        { "portfolio": ACCOUNT_ID },
        "type":        "market",
        "timeInForce": "oneday",
        "allowMargin": True
    }

    await send_telegram_log(
        f"📤 Отправка заявки:\n"
        f"📈 Тикер: `{symbol}`\n"
        f"📊 Сторона: `{order['side'].upper()}` | Объём: `{order['qty']}`"
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return {
            "price":   float(data.get("price", 0)),
            "order_id": data.get("orderNumber", "N/A"),
            "filled":  data.get("executedQuantity", int(order["qty"])),
            "status":  "success"
        }

    except httpx.HTTPStatusError as e:
        await send_telegram_log(f"❌ HTTP ошибка {e.response.status_code}:\n{e.response.text}")
        logger.error(f"HTTP {e.response.status_code} - {e.response.text}")
        return {"status": "error", "detail": e.response.text}

    except Exception as e:
        await send_telegram_log(f"❌ Ошибка при отправке заявки:\n{e}")
        logger.exception("Ошибка при отправке заявки")
        return {"status": "error", "detail": str(e)}


# ───────────────────── snapshot позиции по одному символу ────────────────────
async def get_position_snapshot(ticker: str) -> dict:
    symbol = get_alor_symbol(ticker)
    token  = await get_access_token()
    url    = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/positions"

    headers = { "Authorization": f"Bearer {token}" }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            positions = resp.json()

        for pos in positions:
            if pos.get("symbol") == symbol:
                return {
                    "qty":      int(pos.get("qty", 0)),
                    "avgPrice": float(pos.get("avgPrice", 0.0))
                }

        return {"qty": 0, "avgPrice": 0.0}

    except Exception as e:
        await send_telegram_log(f"❌ Ошибка получения позиции {ticker}:\n{e}")
        logger.exception("Ошибка get_position_snapshot")
        return {"qty": 0, "avgPrice": 0.0}


# ─────────────────────── все текущие позиции счёта ───────────────────────────
async def get_current_positions() -> dict:
    token  = await get_access_token()
    url    = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/positions"
    headers = { "Authorization": f"Bearer {token}" }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        result = {}
        for pos in data:
            symbol = pos.get("symbol")
            qty    = int(pos.get("qty", 0))
            if qty == 0:
                continue

            # ищем совпадение symbol в TICKER_MAP
            for info in TICKER_MAP.values():
                if info["symbol"] == symbol:
                    result[info["symbol"]] = qty     # ключ = биржевой символ
                    break
        return result

    except Exception as e:
        await send_telegram_log(f"❌ Ошибка get_current_positions:\n{e}")
        logger.exception("Ошибка get_current_positions")
        return {}
