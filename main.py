from fastapi import FastAPI, Request
from trading import process_signal
from alor_api import place_order
from token_manager import get_valid_token
from loguru import logger

app = FastAPI()
logger.add("log.txt", rotation="1 MB", compression="zip")

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    signal_ticker = data.get("signal_ticker")
    action = data.get("action")

    if not signal_ticker or not action:
        return {"error": "Missing signal_ticker or action"}

    logger.info(f"Received signal: {signal_ticker} -> {action}")
    result = process_signal(signal_ticker, action)

    token = get_valid_token()
    for order in result["actions"]:
        order_result = place_order(order, token)
        logger.info(f"Order result: {order_result}")

    return result