from config import TICKER_MAP, MAX_QTY, ADD_QTY
from loguru import logger

CURRENT_POSITIONS = {v["trade"]: 0 for v in TICKER_MAP.values()}

def process_signal(signal_ticker: str, action: str):
    if signal_ticker not in TICKER_MAP:
        return {"error": f"Unknown ticker: {signal_ticker}"}

    info = TICKER_MAP[signal_ticker]
    trade_ticker = info["trade"]
    add_qty = ADD_QTY[trade_ticker]
    max_qty = MAX_QTY[trade_ticker]
    current_pos = CURRENT_POSITIONS.get(trade_ticker, 0)

    if action == "buy":
        new_pos = min(current_pos + add_qty, max_qty)
    elif action == "sell":
        new_pos = max(current_pos - add_qty, -max_qty)
    else:
        return {"error": f"Unknown action: {action}"}

    actions = []

    if (current_pos > 0 and new_pos < 0) or (current_pos < 0 and new_pos > 0):
        actions.append({
            "instrument": trade_ticker,
            "side": "Sell" if current_pos > 0 else "Buy",
            "qty": abs(current_pos),
            "type": "close"
        })
        actions.append({
            "instrument": trade_ticker,
            "side": "Buy" if new_pos > 0 else "Sell",
            "qty": abs(new_pos),
            "type": "open"
        })
    elif new_pos != current_pos:
        side = "Buy" if new_pos > current_pos else "Sell"
        actions.append({
            "instrument": trade_ticker,
            "side": side,
            "qty": abs(new_pos - current_pos),
            "type": "adjust"
        })

    CURRENT_POSITIONS[trade_ticker] = new_pos

    return {
        "signal": signal_ticker,
        "trading": trade_ticker,
        "current_position": current_pos,
        "new_position": new_pos,
        "actions": actions
    }