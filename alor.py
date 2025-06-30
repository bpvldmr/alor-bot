import uuid
import httpx
from config import BASE_URL, ACCOUNT_ID
from auth import get_access_token  # ✅ асинхронная
from telegram_logger import send_telegram_log  # ✅ логирование

async def place_order(order: dict):
    token = await get_access_token()  # ✅ await обязательно!
    url = f"{BASE_URL}/commandapi/warptrans/TRADE/v2/client/orders/actions/market"

    headers = {
        "Authorization": f"Bearer {token}",
        "X-REQID": str(uuid.uuid4()),
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {
        "side": order["side"].upper(),           # ✅ "BUY" или "SELL"
        "quantity": int(order["qty"]),           # ✅ целое число
        "instrument": {
            "symbol": order["symbol"],           # ✅ "CNY-9.25" или "NG-7.25"
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

    await send_telegram_log(
        f"📤 Отправка рыночной заявки:\n"
        f"📈 Тикер: `{order['instrument']}`\n"
        f"📊 Сторона: `{order['side'].upper()}` | Объём: `{order['qty']}`\n"
        f"🔗 URL: `{url}`"
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        await send_telegram_log(
            f"✅ Успешная заявка исполнена\n"
            f"🧾 Ответ:\n```json\n{data}\n```"
        )

        return {
            "price": data.get("price", 0),
            "order_id": data.get("orderNumber", "N/A"),
            "status": "success"
        }

    except httpx.HTTPStatusError as e:
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
        await send_telegram_log(f"❌ Ошибка при отправке заявки:\n{str(e)}")
        return {"status": "error", "detail": str(e)}
