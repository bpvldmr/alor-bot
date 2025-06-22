# trading.py

from datetime import datetime
from config import TICKER_MAP, START_QTY, MAX_QTY, ADD_QTY, ACCOUNT_ID

# Текущее состояние позиций
current_positions = {
    "CRU5": 0,
    "NGN5": 0
}

def is_weekend():
    today = datetime.utcnow().weekday()  # 0 = Пн, 6 = Вс
    return today in [5, 6]  # Сб или Вс

def place_market_order(ticker, side, quantity):
    # Здесь будет вызов API ALOR на исполнение заявки
    print(f"➡️ {side.upper()} {quantity} контрактов по {ticker} (рынок)")

def close_position(ticker):
    qty = current_positions[ticker]
    if qty > 0:
        place_market_order(ticker, "sell", qty)
    elif qty < 0:
        place_market_order(ticker, "buy", abs(qty))
    current_positions[ticker] = 0
    print(f"❌ Позиция по {ticker} закрыта")

def handle_signal(tv_ticker, signal):  # signal = "LONG" или "SHORT"
    if is_weekend():
        print(f"⛔ Сигнал получен в выходной день. Торговля запрещена.")
        return

    if tv_ticker not in TICKER_MAP:
        print(f"⚠️ Неизвестный тикер: {tv_ticker}")
        return

    ticker = TICKER_MAP[tv_ticker]["trade"]
    direction = 1 if signal == "LONG" else -1
    current_qty = current_positions[ticker]

    # Усреднение по направлению
    if current_qty * direction > 0:
        new_qty = current_qty + ADD_QTY[ticker]
        if abs(new_qty) > MAX_QTY[ticker]:
            print(f"🚫 Достигнут лимит по {ticker}. Пропуск.")
            return
        place_market_order(ticker, signal.lower(), ADD_QTY[ticker])
        current_positions[ticker] = new_qty
        print(f"➕ Усреднение: теперь {ticker} = {new_qty} контрактов")

    # Обратный сигнал — закрываем и открываем новую позицию
    elif current_qty * direction < 0:
        close_position(ticker)
        start_qty = START_QTY[ticker]
        place_market_order(ticker, signal.lower(), start_qty)
        current_positions[ticker] = direction * start_qty
        print(f"🔄 Обратный сигнал: открыта новая позиция по {ticker} = {start_qty}")

    # Новая позиция
    elif current_qty == 0:
        start_qty = START_QTY[ticker]
        place_market_order(ticker, signal.lower(), start_qty)
        current_positions[ticker] = direction * start_qty
        print(f"✅ Открыта позиция по {ticker} = {start_qty}")
