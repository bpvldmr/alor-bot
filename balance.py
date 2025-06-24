from fastapi import APIRouter, HTTPException
from auth import get_access_token
import os
import httpx
import requests

router = APIRouter()

BASE_URL = "https://api.alor.ru"
ACCOUNT_ID = os.getenv("ACCOUNT_ID")

@router.get("/balance")
async def get_balance():
    """
    Возвращает доступный к выводу баланс по счёту ALOR.
    """
    token = get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка запроса: {str(e)}")

    balance = data.get("cashAvailableForWithdraw", 0.0)
    return {"balance": balance}


@router.get("/debug_balance")
def debug_balance():
    """
    Возвращает полный JSON-ответ от Alor (для отладки).
    """
    token = get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка запроса: {str(e)}")
