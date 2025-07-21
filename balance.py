from fastapi import APIRouter, HTTPException
from auth import get_access_token
from loguru import logger
import httpx
import locale

# ─────────────────────────── локаль для разделителей «1 234 567,89» ───────────────────────────
try:
    # На большинстве серверов ru_RU.UTF-8 не предустановлен; ловим ошибку и падаем на дефолт
    locale.setlocale(locale.LC_NUMERIC, "ru_RU.UTF-8")
except locale.Error:
    logger.warning("Locale ru_RU.UTF-8 not found, using the default locale")
    locale.setlocale(locale.LC_NUMERIC, "")  # пустая строка → системная локаль
# ────────────────────────────────────────────────────────────────────────────────────────────────

router = APIRouter()

BASE_URL = "https://api.alor.ru"
ACCOUNT_ID = "7502QAB"
TELEGRAM_TOKEN = "7610150119:AAGMzDYUdcI6QQuvt-Vsg8U4s1VSYarLIe0"
CHAT_ID = "205721225"

# ───────────────────────── исправленная функция ──────────────────────────
def build_portfolio_summary(summary: dict,
                            profit_total: float = 0.0,
                            base_balance: float = 1.0) -> str:
    """
    Формирует компактный отчёт о состоянии счёта.
    Используются только четыре показателя, как запросил пользователь.
    """
    buying_power      = summary.get("buyingPower", 0)
    portfolio_value   = summary.get("portfolioEvaluation", 0)
    force_close_risk  = summary.get("riskBeforeForcePositionClosing", 0)
    rub_funds         = summary.get("buyingPowerByCurrency", [{}])[0].get("buyingPower", 0)

    report = (
        f"💼 *Сводка по счёту {ACCOUNT_ID}*\n\n"
        f"💰 *Свободные средства:* {buying_power:,.2f} ₽\n"
        f"💼 *Оценка портфеля:* {portfolio_value:,.2f} ₽\n\n"
        f"💣 *Риск до маржин-колла:* {force_close_risk:,.2f} ₽\n\n"
        f"💵 *В RUB:* {rub_funds:,.2f} ₽"
    )
    return report
# ──────────────────────────────────────────────────────────────────────────


async def send_balance_to_telegram(summary: dict,
                                   profit_total: float = 0.0,
                                   base_balance: float = 1.0):
    try:
        report = build_portfolio_summary(summary, profit_total, base_balance)

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
    except Exception:
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
    except Exception:
        logger.exception("Ошибка при получении баланса")
        raise HTTPException(status_code=502, detail="Ошибка запроса к Alor")

    await send_balance_to_telegram(data)          # profit_total / base_balance необязательны
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
    except Exception:
        logger.exception("Ошибка при отладке запроса")
        raise HTTPException(status_code=502, detail="Ошибка запроса к Alor")
