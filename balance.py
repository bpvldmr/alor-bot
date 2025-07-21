# balance.py
# ─────────────────────────────────────────────────────────────────────────────
# 2025‑07‑21  patch‑2
#
# • Добавлена совместимая обёртка async log_balance() — теперь trading.py
#   может импортировать её без ошибки.
# • Логика расчёта и отправки отчёта не изменена.
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import APIRouter, HTTPException
from auth     import get_access_token
from loguru   import logger
import httpx, locale

# ────────── локаль «1 234 567,89» ───────────────────────────────────────────
try:
    locale.setlocale(locale.LC_NUMERIC, "ru_RU.UTF-8")
except locale.Error:
    logger.warning("Locale ru_RU.UTF-8 not found, using default")
    locale.setlocale(locale.LC_NUMERIC, "")
# ────────────────────────────────────────────────────────────────────────────

router = APIRouter()

BASE_URL       = "https://api.alor.ru"
ACCOUNT_ID     = "7502QAB"
TELEGRAM_TOKEN = "7610150119:AAGMzDYUdcI6QQuvt-Vsg8U4s1VSYarLIe0"
CHAT_ID        = "205721225"

# ───────── helper: строим текст отчёта ──────────────────────────────────────
def build_portfolio_summary(summary: dict,
                            profit_total: float = 0.0,
                            base_balance: float = 1.0) -> str:
    buying_power     = summary.get("buyingPower", 0)
    portfolio_value  = summary.get("portfolioEvaluation", 0)
    force_close_risk = summary.get("riskBeforeForcePositionClosing", 0)
    rub_funds        = summary.get("buyingPowerByCurrency", [{}])[0].get("buyingPower", 0)

    return (
        f"💼 *Сводка по счёту {ACCOUNT_ID}*\n\n"
        f"💰 *Свободные средства:* {buying_power:,.2f} ₽\n"
        f"💼 *Оценка портфеля:* {portfolio_value:,.2f} ₽\n\n"
        f"💣 *Риск до маржин‑колла:* {force_close_risk:,.2f} ₽\n\n"
        f"💵 *В RUB:* {rub_funds:,.2f} ₽"
    )

# ───────── send to Telegram ─────────────────────────────────────────────────
async def send_balance_to_telegram(summary: dict,
                                   profit_total: float = 0.0,
                                   base_balance: float = 1.0):
    try:
        report  = build_portfolio_summary(summary, profit_total, base_balance)
        url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": report, "parse_mode": "Markdown"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            logger.info("📤 Баланс отправлен в Telegram")
    except Exception:
        logger.exception("❌ Ошибка при отправке баланса в Telegram")

# ───────── PUBLIC: REST‑ендпоинты ───────────────────────────────────────────
@router.get("/balance")
async def get_balance():
    token   = await get_access_token()
    url     = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

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

    await send_balance_to_telegram(data)
    return {"balance": data.get("cashAvailableForWithdrawal", 0.0)}

@router.get("/debug_balance")
async def debug_balance():
    token   = await get_access_token()
    url     = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

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

# ───────── совместимость: log_balance ───────────────────────────────────────
async def log_balance() -> None:
    """
    Совместимая обёртка для trading.py.
    Просто вызывает get_balance() чтобы сгенерировать отчёт.
    """
    try:
        await get_balance()
    except Exception:
        # get_balance уже залогирует и пробросит детали
        pass
# ────────────────────────────────────────────────────────────────────────────
