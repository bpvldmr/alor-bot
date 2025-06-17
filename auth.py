
import requests

REFRESH_TOKEN = "a0facbb9-aadd-4f67-88e0-1204dcd392b5"
CLIENT_ID = "93e214f3a9e74524a075"
CLIENT_SECRET = "TmAUmTAz6JJbhLZZguRzoP3p5dJ9RUrvlAzz19Y9U0U="
REDIRECT_URI = "https://oauth.alor.ru/blank.html"

def get_access_token():
    url = "https://oauth.alor.ru/refresh"
    payload = {
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "refresh_token"
    }

    response = requests.post(url, data=payload)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        print("❌ Ошибка получения токена:", response.text)
        return None
