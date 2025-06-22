# config.py

# Соответствие тикеров TradingView и тикеров Alor
TICKER_MAP = {
    "MOEX:CRU2025": {"trade": "CRU5"},
    "MOEX:NGN2025": {"trade": "NGN5"}
}

# Начальное количество контрактов
START_QTY = {
    "CRU5": 5,
    "NGN5": 3
}

# Максимальное количество контрактов
MAX_QTY = {
    "CRU5": 9,
    "NGN5": 5
}

# Количество добавки при усреднении
ADD_QTY = {
    "CRU5": 2,
    "NGN5": 1
}

# Твой ID аккаунта на ALOR
ACCOUNT_ID = "7502QAB"
