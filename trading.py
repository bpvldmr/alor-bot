from config import TICKER_MAP

CURRENT_POSITIONS = {
    "CRU9": 0,
    "NGN5": 0
}

def process_signal(signal_ticker: str, action: str):
    if signal_ticker not in TICKER_MAP:
        return {"error": f"Неизвестный сигнал: {signal_ticker}"}

    trade_info = TICKER_MAP[signal_ticker]
    trade_ticker = trade_info["trade"]
    target_qty = trade_info["qty"]
    current_pos = CURRENT_POSITIONS.get(trade_ticker, 0)

    desired_pos = target_qty if action == "buy" else -target_qty
    actions = []

    if current_pos != 0 and current_pos != desired_pos:
        reverse = "Sell" if current_pos > 0 else "Buy"
        actions.append({
            "instrument": trade_ticker,
            "side": reverse,
            "qty": abs(current_pos),
            "type": "close"
        })

    if current_pos != desired_pos:
        open_side = "Buy" if desired_pos > 0 else "Sell"
        actions.append({
            "instrument": trade_ticker,
            "side": open_side,
            "qty": abs(desired_pos),
            "type": "open"
        })

    CURRENT_POSITIONS[trade_ticker] = desired_pos

    return {
        "signal": signal_ticker,
        "trading": trade_ticker,
        "current_position": current_pos,
        "new_position": desired_pos,
        "actions": actions
    }
