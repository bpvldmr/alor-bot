from fastapi import APIRouter, HTTPException
from auth import get_access_token
from loguru import logger
import httpx

router = APIRouter()

BASE_URL = "https://api.alor.ru"
ACCOUNT_ID = "7502QAB"
TELEGRAM_TOKEN = "7610150119:AAGMzDYUdcI6QQuvt-Vsg8U4s1VSYarLIe0"
CHAT_ID = "205721225"


def build_portfolio_summary(summary: dict, profit_total: float, base_balance: float) -> str:
    buying_power = summary.get("buyingPower", 0)
    portfolio_value = summary.get("portfolioEvaluation", 0)
    profit_unrealized = summary.get("profit", 0)
    profit_rate = summary.get("profitRate", 0)
    morning_funds = summary.get("buyingPowerAtMorning", 0)
    force_close_risk = summary.get("riskBeforeForcePositionClosing", 0)
    margin1 = summary.get("initialMargin", 0)
    margin2 = summary.get("correctedMargin", 0)
    rub_funds = summary.get("buyingPowerByCurrency", [{}])[0].get("buyingPower", 0)

    # Защита от деления на ноль
    full_yield = (profit_total / base_balance) * 100 if base_balance else 0

    report = f"""💼 *Сводка по счёту {ACCOUNT_ID}*

💰 *Свободные средства:* {buying_power:,.2f} ₽
💼 *Оценка портфеля:* {portfolio_value:,.2f} ₽
📉 *Нереализ. прибыль:* {profit_unrealized:+.2f} ₽ ({profit_rate:+.2f}%)
📈 *Доходность с начала:* {full_yield:+.2f}%
📊 *Сальдо сделок:* {profit_total:+.2f} ₽
🕗 *Средства утром:* {morning_funds:,.2f} ₽
💣 *Риск до маржин-колла:* {force_close_risk:,.2f} ₽
🏦 *Маржа:* {margin1} / {margin2}
💵 *В RUB:* {rub_funds:,.2f} ₽
"""
    return report


async def send_balance_to_telegram(summary: dict, profit_total: float, base_balance: float):
    try:
        report = build_portfolio_summary(summary, profit_total, base_balance or 1)

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": report,
            "parse_mode": "Markdown"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info("📤 Баланс успешно отправлен в Telegram")
    except Exception as e:
        logger.exception("❌ Ошибка при отправке баланса в Telegram")


@router.get("/balance")
async def get_balance():
    token = await get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Ошибка запроса: {e.response.status_code}")
    except Exception as e:
        logger.exception("Ошибка при получении баланса")
        raise HTTPException(status_code=502, detail=f"Ошибка запроса: {str(e)}")

    # ❗ Без передачи profit_total / base_balance тут send_balance_to_telegram вызовет ошибку
    await send_balance_to_telegram(data, profit_total=0, base_balance=1)  # Заглушка

    balance = data.get("cashAvailableForWithdrawal", 0.0)
    return {"balance": balance}


@router.get("/debug_balance")
async def debug_balance():
    token = await get_access_token()
    url = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Ошибка запроса: {e.response.status_code}")
    except Exception as e:
        logger.exception("Ошибка при отладке запроса")
        raise HTTPException(status_code=502, detail=f"Ошибка запроса: {str(e)}")
