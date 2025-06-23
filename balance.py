import httpx
from fastapi import APIRouter, HTTPException
from config import ACCOUNT_ID, get_access_token

router = APIRouter()  # ✅ это имя нужно для server.py

@router.get("/balance")
async def get_balance():
    """
    Возвращает текущий баланс в рублях по FORTS-счёту.
    Эндпоинт: https://api.alor.ru/md/v2/Clients/legacy/MOEX/{ACCOUNT_ID}/money
    """
    token = get_access_token()
    url = f"https://api.alor.ru/md/v2/Clients/legacy/MOEX/{ACCOUNT_ID}/money"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = httpx.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Ошибка при запросе баланса: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    data = resp.json()

    # В ответе — список позиций money, ищем валюту RUB
    balance = 0.0
    for entry in data.get("money", []):
        if entry.get("currency") in ("RUB", "RUR"):
            balance = float(entry.get("value", 0))
            break

    return {"balance": balance}
