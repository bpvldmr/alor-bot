from datetime import datetime
from config import TICKER_MAP, START_QTY, MAX_QTY, ADD_QTY, ACCOUNT_ID
from loguru import logger

# Текущее состояние позиций
current_positions = {
    "CRU5": 0,
    "NGN5": 0
}

def is_weekend():
    today = datetime.utcnow().weekday()  # 0 = Пн, 6 = Вс
    return today in [5, 6]  # Суббота или Воскресенье

def place_market_order(ticker, side, quantity):
    # Здесь будет вызов API ALOR
    logger.info(f"➡️ {side.upper()} {quantity} контрактов по {ticker} (рынок)")
    return {
        "status": "order_sent",
        "ticker": ticker,
        "side": side,
        "qty": quantity
    }

def close_position(ticker):
    qty = current_positions[ticker]
    if qty > 0:
        place_market_order(ticker, "sell", qty)
    elif qty < 0:
        place_market_order(ticker, "buy", abs(qty))
    current_positions[ticker] = 0
    logger.info(f"❌ Позиция по {ticker} закрыта")

def process_signal(signal_ticker: str, action: str):
    action = action.upper()

    if is_weekend():
        logger.warning("⛔ Сигнал получен в выходной день. Торговля запрещена.")
        return {"error": "Выходной день. Торговля запрещена."}

    if signal_ticker not in TICKER_MAP:
        logger.error(f"⚠️ Неизвестный тикер: {signal_ticker}")
        return {"error": f"Неизвестный тикер: {signal_ticker}"}

    if action not in ["LONG", "SHORT"]:
        logger.error(f"Unknown action: {action}")
        return {"error": f"Unknown action: {action}"}

    ticker = TICKER_MAP[signal_ticker]["trade"]
    direction = 1 if action == "LONG" else -1
    current_qty = current_positions[ticker]

    logger.debug(f"Обработка сигнала: {signal_ticker} → {ticker}, действие: {action}, текущее: {current_qty}")

    # Усреднение в ту же сторону
    if current_qty * direction > 0:
        new_qty = current_qty + ADD_QTY[ticker]
        if abs(new_qty) > MAX_QTY[ticker]:
            logger.warning(f"🚫 Достигнут лимит по {ticker}. Пропуск.")
            return {"status": "limit_reached", "ticker": ticker}
        place_market_order(ticker, action.lower(), ADD_QTY[ticker])
        current_positions[ticker] = new_qty
        return {"status": "added", "ticker": ticker, "new_qty": new_qty}

    # Обратный сигнал — закрыть старую и открыть новую
    elif current_qty * direction < 0:
        close_position(ticker)
        start_qty = START_QTY[ticker]
        place_market_order(ticker, action.lower(), start_qty)
        current_positions[ticker] = direction * start_qty
        return {"status": "reversed", "ticker": ticker, "qty": start_qty}

    # Первая позиция
    elif current_qty == 0:
        start_qty = START_QTY[ticker]
        place_market_order(ticker, action.lower(), start_qty)
        current_positions[ticker] = direction * start_qty
        return {"status": "opened", "ticker": ticker, "qty": start_qty}
