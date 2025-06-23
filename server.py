import asyncio
from fastapi import FastAPI
from loguru import logger
from webhook import router as webhook_router
from balance import balance_router
from auth import get_access_token

app = FastAPI()
app.include_router(webhook_router)
app.include_router(balance_router)   # <-- вот здесь

@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Bot started")
    asyncio.create_task(token_refresher())

async def token_refresher():
    while True:
        try:
            get_access_token()
            logger.debug("🔁 Token refreshed")
        except Exception as e:
            logger.error(f"❌ Refresh error: {e}")
        await asyncio.sleep(3300)
