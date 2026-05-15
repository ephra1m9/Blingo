import os
import re

CHANNEL_ID = -1003956618651
CHANNEL_URL = "https://t.me/BlingoCom"

STEAM_LOGIN_RE = re.compile(r'^[a-zA-Z0-9_]{2,32}$')

# Минимальный платёж
MIN_AMOUNT = 20
# Максимальный платёж
MAX_AMOUNT = 100_000
# Комиссия в процентах (целое число, например 10 = 10%)
COMMISSION = 3

# Статусы заказа
ORDER_STATUS = {
    "0": "Создан",
    "1": "Оплачен",
    "2": "Выполнен",
    "3": "Отменён"
}

# Pay4Game API
PAYFORGAME_API_KEY: str = os.getenv("PAYFORGAME_API_KEY", "")
PAYFORGAME_SECRET: str = os.getenv("PAYFORGAME_SECRET", "")
PAY4GAME_RETURN_URL: str = os.getenv("PAY4GAME_RETURN_URL", "")

# Секретный ключ для API-запросов от сайта
BOT_SECRET_KEY: str = os.getenv("BOT_SECRET_KEY", "")

# Порт для webhook-сервера
WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8080"))
