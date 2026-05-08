import os
import re


STEAM_LOGIN_RE = re.compile(r'^[a-zA-Z0-9_]{2,32}$')

# Минимальный платёж
MIN_AMOUNT = 10
# Максимальный платёж
MAX_AMOUNT = 15_000
# Комиссия в процентах (целое число, например 10 = 10%)
COMMISSION = 10

# Статусы заказа
ORDER_STATUS = {
    "0": "Создан",
    "1": "Оплачен",
    "2": "Выполнен",
    "3": "Отменён"
}

# Dessly API
DESSLY_API_KEY: str = os.getenv("DESSLY_API_KEY", "")

# Порт для webhook-сервера
WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8080"))