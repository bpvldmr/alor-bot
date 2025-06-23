

from datetime import datetime
from config import (
    TICKER_MAP, START_QTY, MAX_QTY, ADD_QTY,
    get_access_token, get_current_balance
)
from telegram_logger import send_telegram_log
from alor import place_order

# Текущие позиции и цены входа
current_positions = {info["trade"]: 0 for info in TICKER_MAP.values()}
entry_prices = {}

def is_weekend():
    # 5 = суббота, 6 = воскресенье
    return datetime.utcnow().weekday() in (5, 6)

def execute_market_order(ticker: str, side: str, qty: int):
    """
    Отправляем рыночную заявку и ждём её исполнения.
    Возвращает цену исполнения (float) или None при ошибке/отклонении.
    """
    token = get_access_token()
    order = {"side": side.upper(), "qty": qty, "instrument": ticker}
    resp = place_order(order, token)

    # Ошибка на уровне API
    if "error" in resp:
        send_telegram_log(f"❌ Заявка {side.upper()} {qty} {ticker} не отправлена: {resp['error']}")
        return None

    status = resp.get("status")
    price = resp.get("price", 0)
    order_id = resp.get("order_id", "—")

    if status == "filled":
        send_telegram_log(
            f"✅ Заявка исполнена: {side.upper()} {qty} {ticker} @ {price:.2f} ₽\n"
            f"🆔 Order ID: {order_id}"
        )
        return price

    # Если отклонена или отменена
    send_telegram_log(f"❌ Заявка {side.upper()} {qty} {ticker} {status.upper()}")
    return None

def close_position(ticker: str):
    qty = current_positions.get(ticker, 0)
    if qty == 0:
        return

    side = "sell" if qty > 0 else "buy"
    fill_price = execute_market_order(ticker, side, abs(qty))
    if fill_price is None:
        return  # не закрыли — выходим

    entry = entry_prices.get(ticker, 0)
    pnl = (fill_price - entry) * qty
    pnl_pct = (pnl / (entry * abs(qty)) * 100) if entry else 0.0
    current_positions[ticker] = 0

    balance = get_current_balance()
    send_telegram_log(
        f"❌ Закрыта позиция {ticker}: {qty:+} контрактов @ {fill_price:.2f} ₽\n"
        f"📊 PnL: {pnl:+.2f} ₽ ({pnl_pct:+.2f} %)\n"
        f"💰 Баланс: {balance:.2f} ₽\n"
        f"📌 Открытых позиций нет"
    )

async def handle_trading_signal(tv_ticker: str, signal: str):
    """
    Основная точка входа для webhook’а.
    signal — "LONG" или "SHORT"
    """
    if is_weekend():
        send_telegram_log(f"⛔ Торговля запрещена — выходной, сигнал {signal} по {tv_ticker}")
        return {"error": "Weekend"}

    if tv_ticker not in TICKER_MAP:
        send_telegram_log(f"⚠️ Неизвестный тикер из TV: {tv_ticker}")
        return {"error": "Unknown ticker"}

    ticker = TICKER_MAP[tv_ticker]["trade"]
    direction = 1 if signal == "LONG" else -1
    current_qty = current_positions.get(ticker, 0)

    # 1) Усреднение (тот же знак)
    if current_qty * direction > 0:
        new_qty = current_qty + ADD_QTY[ticker]
        if abs(new_qty) > MAX_QTY[ticker]:
            send_telegram_log(f"🚫 Лимит позиции {ticker} = {MAX_QTY[ticker]}, усреднение пропущено")
            return {"error": "Limit exceeded"}

        price = execute_market_order(ticker, signal.lower(), ADD_QTY[ticker])
        if price is not None:
            current_positions[ticker] = new_qty
            entry_prices[ticker] = (
                (entry_prices.get(ticker, 0) * abs(current_qty) + price * ADD_QTY[ticker])
                / abs(new_qty)
            )
            balance = get_current_balance()
            send_telegram_log(
                f"➕ Усреднение {ticker}: теперь {new_qty:+} контрактов @ {entry_prices[ticker]:.2f} ₽\n"
                f"💰 Баланс: {balance:.2f} ₽"
            )

    # 2) Встречный сигнал (закрываем старую, открываем новую)
    elif current_qty * direction < 0:
        close_position(ticker)

        start_qty = START_QTY[ticker]
        price = execute_market_order(ticker, signal.lower(), start_qty)
        if price is not None:
            current_positions[ticker] = direction * start_qty
            entry_prices[ticker] = price
            balance = get_current_balance()
            send_telegram_log(
                f"✅ Открыта новая позиция {ticker}: {direction * start_qty:+} @ {price:.2f} ₽\n"
                f"💰 Баланс: {balance:.2f} ₽"
            )

    # 3) Нет позиции — просто открываем
    elif current_qty == 0:
        start_qty = START_QTY[ticker]
        price = execute_market_order(ticker, signal.lower(), start_qty)
        if price is not None:
            current_positions[ticker] = direction * start_qty
            entry_prices[ticker] = price
            balance = get_current_balance()
            send_telegram_log(
                f"✅ Открыта позиция {ticker}: {direction * start_qty:+} @ {price:.2f} ₽\n"
                f"💰 Баланс: {balance:.2f} ₽"
            )

    return {"status": "done"}

# Экспорт для webhook
process_signal = handle_trading_signal
