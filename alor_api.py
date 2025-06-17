import httpx
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
        r = httpx.post(url, json=body, headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}