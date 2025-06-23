import httpx
import time
from config import ACCOUNT_ID
from telegram_logger import send_telegram_log  # лог в Telegram

BASE_URL = "https://api.alor.ru"

def place_order(order, token):
    url = f"{BASE_URL}/commandapi/warptrans/TRADE/v2/client/{ACCOUNT_ID}/orders"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    side = order["side"]
    qty = order["qty"]
    instrument = order["instrument"]

    body = {
        "side": side,
        "quantity": qty,
        "instrument": {
            "symbol": instrument,
            "exchange": "FORTS"  # ✅ всегда FORTS
        },
        "orderType": "Market",
        "timeInForce": "Day"
    }

    try:
        # 🟡 Лог отправки заявки
        send_telegram_log(f"📤 Отправка заявки в ALOR:\n{body}")

        response = httpx.post(url, json=body, headers=headers, timeout=10)
        data = response.json()

        if "orderNumber" not in data:
            send_telegram_log(f"❌ Ошибка: нет orderNumber в ответе ALOR:\n{data}")
            return {"error": "Нет orderNumber в ответе", "raw": data}

        order_id = data["orderNumber"]

        # 🔄 Ждём исполнения
        for _ in range(10):
            status_url = f"{BASE_URL}/commandapi/warptrans/TRADE/v2/client/{ACCOUNT_ID}/orders/{order_id}"
            status_resp = httpx.get(status_url, headers=headers)
            status_data = status_resp.json()

            if status_data.get("status") == "filled":
                price = status_data.get("filledPrice") or status_data.get("price", 0)
                send_telegram_log(f"✅ Заявка исполнена: {side.upper()} {qty} {instrument} @ {price}")
                return {
                    "price": price,
                    "status": "filled",
                    "order_id": order_id
                }

            elif status_data.get("status") in ["cancelled", "rejected"]:
                send_telegram_log(f"❌ Заявка отклонена: {status_data}")
                return {"error": f"Заявка отклонена: {status_data.get('status')}", "details": status_data}

            time.sleep(0.5)

        send_telegram_log("❌ Заявка не была исполнена за 5 секунд.")
        return {"error": "Заявка не была исполнена за отведённое время"}

    except Exception as e:
        send_telegram_log(f"❌ Ошибка при отправке заявки в ALOR: {e}")
        return {"error": str(e)}
