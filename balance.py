from fastapi import APIRouter, HTTPException
from auth import get_access_token
import httpx
from loguru import logger

router = APIRouter()

BASE_URL = "https://api.alor.ru"
ACCOUNT_ID = "7502QAB"
TELEGRAM_TOKEN = "7610150119:AAGMzDYUdcI6QQuvt-Vsg8U4s1VSYarLIe0"
CHAT_ID = "205721225"

async def send_balance_to_telegram(summary: dict):
    message = f"""📊 *Сводка по счёту {ACCOUNT_ID}*

💰 *Свободные средства:* {summary.get("buyingPower", 0):,.2f} ₽
💼 *Оценка портфеля:* {summary.get("portfolioEvaluation", 0):,.2f} ₽
📉 *Прибыль:* {summary.get("profit", 0):,.2f} ₽
📉 *Доходность:* {summary.get("profitRate", 0):.2f}%
🕗 *Средства утром:* {summary.get("buyingPowerAtMorning", 0):,.2f} ₽
💣 *Риск до принудительного закрытия:* {summary.get("riskBeforeForcePositionClosing", 0):,.2f} ₽
🏦 *Маржа:* {summary.get("initialMargin", 0)} / {summary.get("correctedMargin", 0)}
💵 *В RUB:* {summary.get("buyingPowerByCurrency", [{}])[0].get("buyingPower", 0):,.2f} ₽
"""

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info("📤 Баланс успешно отправлен в Telegram")
    except Exception as e:
        logger.exception("❌ Ошибка при отправке баланса в Telegram")

@router.get("/balance")
async def get_balance():
    """
    Возвращает доступный к выводу баланс по счёту ALOR (через актуальный endpoint /summary).
    Также отправляет сводку в Telegram.
    """
    token = get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/{ACCOUNT_ID}/summary"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    logger.debug(f"📡 URL: {url}")
    logger.debug(f"🔐 Token: {token[:20]}...")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.debug(f"📊 Ответ от Alor: {data}")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP ошибка: {e.response.status_code}")
        raise HTTPException(status_code=502, detail=f"Ошибка запроса: {e.response.status_code}")
    except Exception as e:
        logger.exception("Ошибка при получении баланса")
        raise HTTPException(status_code=502, detail=f"Ошибка запроса: {str(e)}")

    await send_balance_to_telegram(data)
    balance = data.get("cashAvailableForWithdrawal", 0.0)
    return {"balance": balance}


@router.get("/debug_balance")
async def debug_balance():
    """
    Возвращает полный JSON-ответ от Alor (через актуальный endpoint /summary).
    """
    token = get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/MOEX{ACCOUNT_ID}/summary"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    logger.debug(f"🐞 Debug URL: {url}")
    logger.debug(f"🔐 Token: {token[:20]}...")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.debug(f"🐞 Debug response: {data}")
            return data
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP ошибка: {e.response.status_code}")
        raise HTTPException(status_code=502, detail=f"Ошибка запроса: {e.response.status_code}")
    except Exception as e:
        logger.exception("Ошибка при отладке запроса")
        raise HTTPException(status_code=502, detail=f"Ошибка запроса: {str(e)}")
