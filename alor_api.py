import httpx
import time
from config import ACCOUNT_ID

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
            "exchange": "MOEX"
        },
        "orderType": "Market",
        "timeInForce": "Day"
    }

    try:
        response = httpx.post(url, json=body, headers=headers, timeout=10)
        data = response.json()

        if "orderNumber" not in data:
            return {"error": "Нет orderNumber в ответе", "raw": data}

        order_id = data["orderNumber"]

        # 🔄 Ждём подтверждения исполнения
        for _ in range(10):
            status_url = f"{BASE_URL}/commandapi/warptrans/TRADE/v2/client/{ACCOUNT_ID}/orders/{order_id}"
            status_resp = httpx.get(status_url, headers=headers)
            status_data = status_resp.json()

            if status_data.get("status") == "filled":
                return {
                    "price": status_data.get("filledPrice") or status_data.get("price", 0),
                    "status": "filled",
                    "order_id": order_id
                }

            elif status_data.get("status") in ["cancelled", "rejected"]:
                return {"error": f"Заявка отклонена: {status_data.get('status')}"}

            time.sleep(0.5)

        return {"error": "Заявка не была исполнена за отведённое время"}

    except Exception as e:
        return {"error": str(e)}
