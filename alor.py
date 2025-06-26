import requests
import uuid
from config import BASE_URL, ACCOUNT_ID
from auth import get_access_token

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
        "quantity": order["qty"],
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

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # Попытка взять цену исполнения и ID (если они есть)
        return {
            "price": data.get("price", 0),
            "order_id": data.get("orderNumber", "N/A"),
            "status": "success"
        }

    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": str(e)}
