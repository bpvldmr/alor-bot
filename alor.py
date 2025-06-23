
import httpx
import time
import uuid
from config import ACCOUNT_ID

BASE_URL = "https://api.alor.ru"

def place_order(order, token):
    # Правильный HTTP endpoint для создания рыночной заявки
    url = f"{BASE_URL}/commandapi/warptrans/TRADE/v2/client/orders/actions/market"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-REQID": str(uuid.uuid4())  # уникальный ID запроса
    }

    body = {
        "side": order["side"],               # "Buy" или "Sell"
        "quantity": order["qty"],            # количество контрактов
        "instrument": {
            "symbol": order["instrument"],   # например "CRU5"
            "exchange": "FORTS"              # торгуем только на FORTS
        },
        "user": {
            "portfolio": ACCOUNT_ID          # ваш portfolio ID из config
        },
        "timeInForce": "Day",
        "allowMargin": False,
        "checkDuplicates": True
    }

    try:
        # 1) Отправляем заявку
        resp = httpx.post(url, json=body, headers=headers, timeout=10)
    except Exception as e:
        return {"error": f"HTTP error: {e}"}

    # 2) Парсим ответ
    try:
        data = resp.json()
    except Exception:
        return {
            "error": "Невалидный ответ от ALOR (не JSON)",
            "status_code": resp.status_code,
            "text": resp.text
        }

    # 3) Проверяем наличие orderNumber
    if "orderNumber" not in data:
        return {"error": "Нет orderNumber в ответе", "raw": data}

    order_id = data["orderNumber"]

    # 4) Ждём, пока заявка исполнится
    status_url = f"{BASE_URL}/commandapi/warptrans/TRADE/v2/client/orders/{order_id}"
    for _ in range(20):
        st_resp = httpx.get(status_url, headers=headers, timeout=5)
        try:
            st = st_resp.json()
        except Exception:
            return {
                "error": "Невалидный статус-ответ от ALOR",
                "status_code": st_resp.status_code,
                "text": st_resp.text
            }

        status = st.get("status")
        if status == "filled":
            price = st.get("filledPrice") or st.get("price", 0)
            return {
                "price": price,
                "status": "filled",
                "order_id": order_id
            }
        if status in ("cancelled", "rejected"):
            return {"error": f"Заявка отклонена: {status}", "raw": st}

        time.sleep(0.5)

    return {"error": "Заявка не была исполнена за отведённое время", "raw": st}
