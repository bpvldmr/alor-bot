import httpx
import time
import os

access_token = None
token_expiry = 0

def get_valid_token():
    global access_token, token_expiry
    if access_token is None or time.time() > token_expiry - 60:
        access_token = refresh_token()
        token_expiry = time.time() + 3600
    return access_token

def refresh_token():
    data = {
        "refresh_token": os.getenv("REFRESH_TOKEN"),
        "client_id": os.getenv("CLIENT_ID"),
        "client_secret": os.getenv("CLIENT_SECRET"),
        "grant_type": "refresh_token"
    }
    r = httpx.post("https://oauth.alor.ru/refresh", json=data, timeout=10)
    return r.json().get("access_token")