import uuid
import time
import httpx
from config import BASE_URL, ACCOUNT_ID
from auth import get_access_token

async def place_order(order: dict) -> dict:
    """
    order = {"side": "BUY"/"SELL", "qty": int, "instrument": "CRU5"}
    """
    token = await get_access_token()
    reqid = str(uuid.uuid4())
    url = f"{BASE_URL}/commandapi/warptrans/TRADE/v2/client/{ACCOUNT_ID}/orders"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "X-REQID":        reqid
    }
    body = {
        "side":       order["side"],
        "quantity":   order["qty"],
        "instrument": {"symbol": order["instrument"], "exchange": "FORTS"},
        "orderType":  "Market",
        "timeInForce":"Day"
    }

    r = httpx.post(url, json=body, headers=headers, timeout=10)
    # Попытка распарсить JSON
    try:
        data = r.json()
    except ValueError:
        return {
            "error": f"Не JSON в ответе ({r.status_code})",
            "text":  r.text
        }

    if not r.is_success or "orderNumber" not in data:
        return {"error": "orderNumber отсутствует", "raw": data}

    order_id = data["orderNumber"]

    # Ждём исполнения (опционально можно увеличить тайм-аут)
    for _ in range(10):
        status = httpx.get(f"{url}/{order_id}", headers=headers).json()
        st = status.get("status","")
        if st.lower() == "filled":
            return {
                "status":    "filled",
                "price":     status.get("filledPrice",status.get("price",0)),
                "order_id":  order_id
            }
        if st.lower() in ("cancelled","rejected"):
            return {"error": f"Заявка {st.upper()}"}
        time.sleep(0.5)

    return {"error": "Не исполнена за время"}
