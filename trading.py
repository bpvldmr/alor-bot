
import requests
from config import ACCOUNT_ID, TICKER_MAP
from auth import get_access_token

CURRENT_POSITIONS = {
    "CRU5": 0,
    "NGN5": 0
}

BASE_URL = "https://api.alor.ru"

def send_order(instrument, side, quantity):
    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    url = f"{BASE_URL}/commandapi/warptrans/TRADE/v2/client/orders/market"
    payload = {
        "instrument": instrument,
        "side": side,
        "quantity": quantity,
        "client": ACCOUNT_ID,
        "exchange": "MOEX",
        "ticker": instrument
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.ok:
        print(f"✅ Заявка отправлена: {side} {quantity} {instrument}")
    else:
        print("❌ Ошибка отправки заявки:", response.text)

def process_signal(signal_ticker: str, action: str):
    if signal_ticker not in TICKER_MAP:
        return {"error": f"Неизвестный сигнал: {signal_ticker}"}

    trade_info = TICKER_MAP[signal_ticker]
    trade_ticker = trade_info["trade"]
    target_qty = trade_info["qty"]
    current_pos = CURRENT_POSITIONS.get(trade_ticker, 0)

    if (action == "buy" and current_pos > 0) or (action == "sell" and current_pos < 0):
        add_qty = 20 if trade_ticker == "CRU5" else 5
        max_qty = 140 if trade_ticker == "CRU5" else 20
        new_qty = min(abs(current_pos) + add_qty, max_qty)
        CURRENT_POSITIONS[trade_ticker] = new_qty if action == "buy" else -new_qty
        send_order(trade_ticker, "Buy" if action == "buy" else "Sell", add_qty)
        return {"усреднение": f"{trade_ticker} => {new_qty}"}

    if (current_pos > 0 and action == "sell") or (current_pos < 0 and action == "buy"):
        close_side = "Sell" if current_pos > 0 else "Buy"
        send_order(trade_ticker, close_side, abs(current_pos))
        CURRENT_POSITIONS[trade_ticker] = 0

    open_qty = target_qty
    open_side = "Buy" if action == "buy" else "Sell"
    send_order(trade_ticker, open_side, open_qty)
    CURRENT_POSITIONS[trade_ticker] = open_qty if action == "buy" else -open_qty

    return {
        "signal": signal_ticker,
        "trading": trade_ticker,
        "position": CURRENT_POSITIONS[trade_ticker]
    }
