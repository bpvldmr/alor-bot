# alor.py
import requests
import uuid
from config import ALOR_BASE_URL, ACCOUNT_ID
from auth import get_access_token

def place_order(order: dict):
    token = get_access_token()
    url = f"{ALOR_BASE_URL}/commandapi/warptrans/TRADE/v2/client/orders/actions/market"
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
            "instrumentGroup": "FUT"  # ← для срочного рынка фьючерсов
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
        return resp.json()
    except Exception as e:
        return {"error": str(e)}
