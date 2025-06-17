
from fastapi import FastAPI, Request
from trading import process_signal

app = FastAPI()

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    signal_ticker = data.get("signal_ticker")
    action = data.get("action")

    if not signal_ticker or not action:
        return {"error": "Нужно передать signal_ticker и action"}

    result = process_signal(signal_ticker, action)
    return result
