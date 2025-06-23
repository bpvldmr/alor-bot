import os
import time
import httpx

CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
ACCOUNT_ID    = os.getenv("ACCOUNT_ID")

BASE_URL = "https://api.alor.ru"

# ——————————————————————————————
#  Access Token
# ——————————————————————————————

_token_cache        = None
_token_expires_at   = 0

def get_access_token() -> str:
    global _token_cache, _token_expires_at
    if time.time() < _token_expires_at - 60:
        return _token_cache

    resp = httpx.post(
        f"{BASE_URL}/refresh",
        data={
            "refresh_token": REFRESH_TOKEN,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET
        },
        timeout=10
    )
    resp.raise_for_status()
    js = resp.json()
    _token_cache      = js["access_token"]
    _token_expires_at = time.time() + js.get("expires_in", 1800)
    return _token_cache

# ——————————————————————————————
#  Баланс (старый endpoint)
# ——————————————————————————————
def get_current_balance() -> float:
    token = get_access_token()
    url   = f"{BASE_URL}/md/v2/Clients/legacy/MOEX/{ACCOUNT_ID}/money?format=Simple"
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = httpx.get(url, headers=hdrs, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    # возвращаем свободные средства (free) или cash
    return float(data.get("free", data.get("cash", 0.0)))

# ——————————————————————————————
#  Портфель (новый endpoint)
#  GET /md/v2/Clients/:exchange/:portfolio/summary
# ——————————————————————————————
def get_portfolio_summary(exchange: str = "MOEX") -> dict:
    token = get_access_token()
    url   = f"{BASE_URL}/md/v2/Clients/{exchange}/{ACCOUNT_ID}/summary"
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = httpx.get(url, headers=hdrs, timeout=10)
    resp.raise_for_status()
    return resp.json()
