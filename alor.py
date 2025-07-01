import uuid
import httpx
from config import BASE_URL, ACCOUNT_ID
from auth import get_access_token
from telegram_logger import send_telegram_log
from loguru import logger

async def place_order(order: dict):
    token = await get_access_token()
    url = f"{BASE_URL}/commandapi/warptrans/TRADE/v2/client/orders/actions/market"

    headers = {
        "Authorization": f"Bearer {token}",
        "X-REQID": str(uuid.uuid4()),
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {
        "side": order["side"].upper(),
        "quantity": int(order["qty"]),
        "instrument": {
            "symbol": order["symbol"],  # ✅ Тикер вида CNY-9.25
            "exchange": "MOEX",
            "instrumentGroup": "RFUD"
        },
        "comment": "ALGO BOT",
        "user": {
            "portfolio": ACCOUNT_ID
        },
        "type": "market",
        "timeInForce": "oneday",
        "allowMargin": True
    }

    # ✅ Лог: тикер теперь показывает symbol, как ты хочешь
    await send_telegram_log(
        f"📤 Отправка рыночной заявки:\n"
        f"📈 Тикер: `{order['symbol']}`\n"
        f"📊 Сторона: `{order['side'].upper()}` | Объём: `{order['qty']}`\n"
        f"🔗 URL: `{url}`"
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        if "price" not in data:
            await send_telegram_log("⚠️ Ответ от ALOR не содержит цену исполнения (`price`)")

        await send_telegram_log(
            f"✅ Успешная заявка исполнена\n"
            f"🧾 Ответ:\n```json\n{data}\n```"
        )

        return {
            "price": float(data.get("price") or 0),
            "order_id": data.get("orderNumber", "N/A"),
            "filled": data.get("executedQuantity", int(order["qty"])),  # если будет
            "status": "success"
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"❌ HTTP ошибка ALOR: {e.response.status_code} - {e.response.text}")
        await send_telegram_log(
            f"❌ Ошибка HTTP при заявке:\n"
            f"Код: {e.response.status_code}\n"
            f"Ответ:\n```{e.response.text}```"
        )
        return {
            "status": "error",
            "code": e.response.status_code,
            "detail": e.response.text
        }

    except Exception as e:
        logger.error(f"❌ ALOR: Ошибка при отправке заявки: {e}")
        await send_telegram_log(f"❌ Ошибка при отправке заявки:\n{str(e)}")
        return {"status": "error", "detail": str(e)}
