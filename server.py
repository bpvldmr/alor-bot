from fastapi import FastAPI
from main import webhook_router

app = FastAPI()
app.include_router(webhook_router)
