from datetime import datetime
import requests
from config import (
    TICKER_MAP, START_QTY, MAX_QTY, ADD_QTY,
    ACCOUNT_ID, get_access_token
)
from telegram_logger import send_telegram_log

current_positions = {
    "CRU5": 0,
    "NGN5": 0
}
entry_prices = {}  # Цена входа по каждой позиции

def is_weekend():
    today = datetime.utcnow().weekday()
    return today in [5, 6]

def get_current_balance():
    try:
        access_token = get_access_token()
        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"https://api.alor.ru/md/v2/Clients/{ACCOUNT_ID}/summary"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        return float(data.get("Equity", 0))
    except Exception as e:
        print(f"Ошибка получения баланса: {e}")
        return 0

def place_market_order(ticker, side, quantity):
    try:
        access_token = get_access_token()
        headers = {"Authorization": f"Bearer {access_token}"}
        url = "https://api.alor.ru/md/v2/SubmitOrder"
        payload = {
            "instrument": {
                "symbol": ticker,
                "exchange": "MOEX"
            },
            "side": side.upper(),  # BUY или SELL
            "type": "Market",
            "quantity": quantity,
            "account": ACCOUNT_ID
        }
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        fill_price = data.get("price") or 0
        print(f"✅ Исполнено: {side.upper()} {quantity} контрактов по {ticker} @ {fill_price}")
        return float(fill_price)
    except Exception as e:
        print(f"❌ Ошибка при исполнении заявки: {e}")
        return 0

def close_position(ticker):
    qty = current_positions[ticker]
    if qty == 0:
        return

    side = "sell" if qty > 0 else "buy"
    close_price = place_market_order(ticker, side, abs(qty))
    entry_price = entry_prices.get(ticker, 0)
    pnl = (close_price - entry_price) * qty
    pnl_percent = (pnl / (entry_price * abs(qty))) * 100 if entry_price else 0

    current_positions[ticker] = 0
    balance = get_current_balance()
    log_message = (
        f"❌ Закрыта позиция по {ticker}\n"
        f"📊 Результат: {pnl:+.2f}₽ ({pnl_percent:+.2f}%)\n"
        f"💰 Баланс: {balance:.2f}₽\n"
        f"📌 Открытых позиций нет"
    )
    send_telegram_log(log_message)

def handle_signal(tv_ticker, signal):
    if is_weekend():
        msg = f"⛔ Сигнал {signal} по {tv_ticker} отклонён — выходной день."
        print(msg)
        send_telegram_log(msg)
        return {"error": "Выходной день. Торговля запрещена."}

    if tv_ticker not in TICKER_MAP:
        print("⚠️ Неизвестный тикер")
        return {"error": "Неизвестный тикер"}

    ticker = TICKER_MAP[tv_ticker]["trade"]
    direction = 1 if signal == "LONG" else -1
    current_qty = current_positions[ticker]

    if current_qty * direction > 0:
        new_qty = current_qty + ADD_QTY[ticker]
        if abs(new_qty) > MAX_QTY[ticker]:
            print(f"🚫 Превышен лимит по {ticker}. Пропуск.")
            return {"error": "Превышен лимит позиции"}
        price = place_market_order(ticker, signal.lower(), ADD_QTY[ticker])
        current_positions[ticker] = new_qty
        log_message = (
            f"➕ Усреднение по {ticker}: теперь {new_qty} контрактов\n"
            f"🔄 Действие: {signal}\n"
            f"💰 Баланс: {get_current_balance():.2f}₽\n"
            f"📌 Позиции: {get_position_snapshot()}"
        )
        send_telegram_log(log_message)

    elif current_qty * direction < 0:
        close_position(ticker)
        start_qty = START_QTY[ticker]
        price = place_market_order(ticker, signal.lower(), start_qty)
        current_positions[ticker] = direction * start_qty
        entry_prices[ticker] = price
        log_message = (
            f"🔄 Обратный сигнал по {ticker}: новая позиция {start_qty} контрактов\n"
            f"🔄 Действие: {signal}\n"
            f"💰 Баланс: {get_current_balance():.2f}₽\n"
            f"📌 Позиции: {get_position_snapshot()}"
        )
        send_telegram_log(log_message)

    elif current_qty == 0:
        start_qty = START_QTY[ticker]
        price = place_market_order(ticker, signal.lower(), start_qty)
        current_positions[ticker] = direction * start_qty
        entry_prices[ticker] = price
        log_message = (
            f"✅ Открыта позиция по {ticker}: {start_qty} контрактов\n"
            f"🔄 Действие: {signal}\n"
            f"💰 Баланс: {get_current_balance():.2f}₽\n"
            f"📌 Позиции: {get_position_snapshot()}"
        )
        send_telegram_log(log_message)

    return {"status": "ok"}

def get_position_snapshot():
    snapshot = ""
    for ticker, qty in current_positions.items():
        if qty != 0:
            price = entry_prices.get(ticker, "?")
            snapshot += f"{ticker}: {qty:+} контрактов @ {price}\n"
    return snapshot if snapshot else "нет"

# === Экспорт правильного имени для webhook ===
process_signal = handle_signal
