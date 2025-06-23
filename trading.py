
import time
from datetime import datetime
from config import (
    TICKER_MAP,
    START_QTY, MAX_QTY, ADD_QTY,
    get_access_token, get_current_balance
)
from telegram_logger import send_telegram_log
from alor import place_order

# Храним текущие позиции и цены входа
current_positions = {info["trade"]: 0 for info in TICKER_MAP.values()}
entry_prices = {info["trade"]: 0.0 for info in TICKER_MAP.values()}


def is_weekend() -> bool:
    """Проверяем, выходной ли сегодня (UTC-суббота или воскресенье)."""
    return datetime.utcnow().weekday() in (5, 6)


def execute_market_order(ticker: str, side: str, qty: int) -> dict:
    """
    Отправляем рыночную заявку через alor.place_order и ждём её исполнения.
    Возвращаем dict с полями:
      - error (str) — если произошла ошибка,
      - status (str): 'filled'/'rejected'/'timeout',
      - price (float)  — цена исполнения,
      - order_id (str) — ID заявки.
    """
    token = get_access_token()
    order = {
        "side": side.capitalize(),  # "Buy" или "Sell"
        "qty": qty,
        "instrument": ticker
    }

    resp = place_order(order, token)
    if "error" in resp:
        return {"error": resp["error"]}

    status = resp.get("status", "")
    price = resp.get("price", 0.0)
    oid   = resp.get("order_id", "—")

    if status == "filled":
        send_telegram_log(
            f"✅ Заявка исполнена: {side.upper()} {qty}×{ticker} @ {price:.2f} ₽\n"
            f"🆔 Order ID: {oid}"
        )
    else:
        send_telegram_log(f"❌ Заявка {side.upper()} {qty}×{ticker} — {status.upper()} (ID {oid})")

    return {"status": status, "price": price, "order_id": oid}


def close_position(ticker: str) -> None:
    """
    Закрывает всю текущую позицию по инструменту.
    Логирует в Telegram итоговое PnL и обновлённый баланс.
    """
    qty = current_positions.get(ticker, 0)
    if qty == 0:
        return

    side = "sell" if qty > 0 else "buy"
    result = execute_market_order(ticker, side, abs(qty))
    if result.get("status") != "filled":
        return  # не получилось закрыть

    fill_price = result["price"]
    entry_price = entry_prices.get(ticker, 0.0)
    pnl = (fill_price - entry_price) * qty
    pnl_pct = (pnl / (entry_price * abs(qty)) * 100) if entry_price else 0.0
    current_positions[ticker] = 0
    entry_prices[ticker] = 0.0

    balance = get_current_balance()
    send_telegram_log(
        f"❌ Позиция {ticker} закрыта: {qty:+} @ {fill_price:.2f} ₽\n"
        f"📊 PnL: {pnl:+.2f} ₽ ({pnl_pct:+.2f}%)\n"
        f"💰 Баланс: {balance:.2f} ₽"
    )


async def process_signal(tv_ticker: str, signal: str) -> dict:
    """
    Основная асинхронная точка входа для webhook’а.
    tv_ticker — ключ из TICKER_MAP, signal — "LONG" или "SHORT".
    Возвращает dict с результатом выполнения.
    """
    signal = signal.upper()
    if signal not in ("LONG", "SHORT"):
        return {"error": "Invalid signal"}

    # 1) Не торгуем в выходные
    if is_weekend():
        msg = f"⛔ Выходной — сигнал {signal} по {tv_ticker} игнорирован."
        send_telegram_log(msg)
        return {"error": "Weekend"}

    # 2) Проверяем тикер
    if tv_ticker not in TICKER_MAP:
        send_telegram_log(f"⚠️ Неизвестный тикер из TV: {tv_ticker}")
        return {"error": "Unknown ticker"}

    ticker = TICKER_MAP[tv_ticker]["trade"]
    direction = 1 if signal == "LONG" else -1
    current_qty = current_positions.get(ticker, 0)

    # 3) Усреднение (тот же знак позиции)
    if current_qty * direction > 0:
        new_qty = current_qty + ADD_QTY[ticker]
        if abs(new_qty) > MAX_QTY[ticker]:
            send_telegram_log(f"🚫 Лимит {ticker}={MAX_QTY[ticker]} превышен, усреднение пропущено.")
            return {"error": "Limit exceeded"}

        res = execute_market_order(ticker, signal.lower(), ADD_QTY[ticker])
        if res.get("status") == "filled":
            # пересчитаем среднюю цену входа
            old_avg = entry_prices[ticker]
            entry_prices[ticker] = (
                (old_avg * abs(current_qty) + res["price"] * ADD_QTY[ticker]) /
                abs(new_qty)
            )
            current_positions[ticker] = new_qty
            balance = get_current_balance()
            send_telegram_log(
                f"➕ Усреднение {ticker}: {new_qty:+} контрактов @ {entry_prices[ticker]:.2f} ₽\n"
                f"💰 Баланс: {balance:.2f} ₽"
            )
        return {"status": "averaged", "position": current_positions[ticker]}

    # 4) Встречный сигнал — закрываем старую и открываем новую
    if current_qty * direction < 0:
        close_position(ticker)
        start_qty = START_QTY[ticker]
        res = execute_market_order(ticker, signal.lower(), start_qty)
        if res.get("status") == "filled":
            current_positions[ticker] = direction * start_qty
            entry_prices[ticker] = res["price"]
            balance = get_current_balance()
            send_telegram_log(
                f"✅ Новая позиция {ticker}: {current_positions[ticker]:+} контрактов @ {res['price']:.2f} ₽\n"
                f"💰 Баланс: {balance:.2f} ₽"
            )
            return {"status": "reversed", "position": current_positions[ticker]}

    # 5) Нет позиции — просто открываем
    if current_qty == 0:
        start_qty = START_QTY[ticker]
        res = execute_market_order(ticker, signal.lower(), start_qty)
        if res.get("status") == "filled":
            current_positions[ticker] = direction * start_qty
            entry_prices[ticker] = res["price"]
            balance = get_current_balance()
            send_telegram_log(
                f"✅ Позиция {ticker}: {current_positions[ticker]:+} контрактов @ {res['price']:.2f} ₽\n"
                f"💰 Баланс: {balance:.2f} ₽"
            )
            return {"status": "opened", "position": current_positions[ticker]}

    return {"status": "no_action"}
