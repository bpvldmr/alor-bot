import requests
import uuid
import asyncio
from config import BASE_URL, ACCOUNT_ID
from auth import get_access_token
from telegram_logger import send_telegram_log  # ✅ логирование

def place_order(order: dict):
    token = get_access_token()
    url = f"{BASE_URL}/commandapi/warptrans/TRADE/v2/client/orders/actions/market"

    headers = {
        "Authorization": f"Bearer {token}",
        "X-REQID": str(uuid.uuid4()),
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {
        "side": order["side"],  # "buy" или "sell"
        "quantity": int(order["qty"]),
        "instrument": {
            "symbol": order["instrument"],
            "exchange": "MOEX",
            "instrumentGroup": "FUT"
        },
        "comment": "ALGO BOT",
        "user": {
            "portfolio": ACCOUNT_ID
        },
        "timeInForce": "day",
        "allowMargin": False
    }

    # ✅ ДО ОТПРАВКИ запроса — логируем параметры
    try:
        asyncio.create_task(send_telegram_log(
            f"📤 Отправка рыночной заявки:\n"
            f"🔗 URL: `{url}`\n"
            f"🪪 Token: `{token[:12]}...`\n"
            f"📦 Payload:\n```json\n{payload}\n```"
        ))
    except:
        pass

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # ✅ Ответ ALOR логируем
        try:
            asyncio.create_task(send_telegram_log(
                f"✅ Успешная заявка\n"
                f"📄 Ответ ALOR:\n```json\n{data}\n```"
            ))
        except:
            pass

        return {
            "price": data.get("price", 0),
            "order_id": data.get("orderNumber", "N/A"),
            "status": "success"
        }

    except requests.exceptions.HTTPError as e:
        try:
            asyncio.create_task(send_telegram_log(
                f"❌ Ошибка HTTP при заявке:\n"
                f"Код: {e.response.status_code}\n"
                f"Ответ:\n```{e.response.text}```"
            ))
        except:
            pass
        return {
            "status": "error",
            "code": e.response.status_code,
            "detail": e.response.text
        }

    except Exception as e:
        try:
            asyncio.create_task(send_telegram_log(
                f"❌ Ошибка при заявке:\n{str(e)}"
            ))
        except:
            pass
        return {"status": "error", "detail": str(e)}
