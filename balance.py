import httpx
from fastapi import APIRouter, HTTPException
from config import ACCOUNT_ID, BASE_URL
from auth import get_access_token  # ✅ теперь берём асинхронную функцию из auth.py

router = APIRouter()  # обязательно router для server.py

@router.get("/balance")
async def get_balance():
    """
    Возвращает текущий баланс в рублях по FORTS-счёту.
    Эндпоинт: https://api.alor.ru/md/v2/Clients/legacy/MOEX/{ACCOUNT_ID}/money
    """
    token = get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/legacy/MOEX/{ACCOUNT_ID}/money?format=Simple"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
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
