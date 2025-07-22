# balance.py
# ─────────────────────────────────────────────────────────────────────────────
# 2025‑07‑22  patch‑3
#
# • Добавлена функция fetch_summary()  — делает _только_ HTTP‑запрос Alor
#   и возвращает свежий summary **без** отправки в Telegram.
# • log_balance() теперь:
#       1) ждёт 2 секунды (чтобы биржа актуализировала данные после сделки);
#       2) вызывает fetch_summary();
#       3) шлёт отчёт в Telegram.
# • REST‑эндпоинты /balance и /debug_balance переиспользуют fetch_summary().
# ─────────────────────────────────────────────────────────────────────────────
import asyncio, locale, httpx
from fastapi import APIRouter, HTTPException
from auth     import get_access_token
from loguru   import logger

router = APIRouter()

BASE_URL       = "https://api.alor.ru"
ACCOUNT_ID     = "7502QAB"
TELEGRAM_TOKEN = "7610150119:AAGMzDYUdcI6QQuvt-Vsg8U4s1VSYarLIe0"
CHAT_ID        = "205721225"

# ───────── локаль для «1 234 567,89» ────────────────────────────────────────
try:
    locale.setlocale(locale.LC_NUMERIC, "ru_RU.UTF-8")
except locale.Error:
    logger.warning("Locale ru_RU.UTF-8 not found, fallback to default")

# ───────── HELPERS ──────────────────────────────────────────────────────────
def build_portfolio_summary(summary: dict) -> str:
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

async def send_balance_to_telegram(summary: dict) -> None:
    try:
        report  = build_portfolio_summary(summary)
        url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": report, "parse_mode": "Markdown"}

        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload)
            logger.info("📤 Баланс отправлен в Telegram")
    except Exception:
        logger.exception("❌ Ошибка при отправке баланса в Telegram")

# ───────── CORE: только запрос Alor ─────────────────────────────────────────
async def fetch_summary() -> dict:
    token   = await get_access_token()
    url     = f"{BASE_URL}/md/v2/Clients/MOEX/{ACCOUNT_ID}/summary"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

# ───────── PUBLIC: вызывается trading.py после сделки ───────────────────────
async def log_balance(delay_sec: int = 2) -> None:
    """Ждём delay_sec, берём самый свежий summary и шлём в Telegram."""
    try:
        await asyncio.sleep(delay_sec)            # даём бирже применить сделку
        summary = await fetch_summary()
        await send_balance_to_telegram(summary)
    except Exception:
        logger.exception("log_balance failed")

# ───────── REST‑эндпоинты (для ручных запросов) ────────────────────────────
@router.get("/balance")
async def get_balance():
    try:
        summary = await fetch_summary()
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"Ошибка запроса: {e.response.status_code}")
    await send_balance_to_telegram(summary)
    return {"balance": summary.get("cashAvailableForWithdrawal", 0.0)}

@router.get("/debug_balance")
async def debug_balance():
    try:
        return await fetch_summary()
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"Ошибка запроса: {e.response.status_code}")
