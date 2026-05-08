import re


STEAM_LOGIN_RE = re.compile(r'^[a-zA-Z0-9_]{2,32}$')

# Минимальный платёж
MIN_AMOUNT = 10
# Максимальный платёж
MAX_AMOUNT = 15_000
# Комиссия
COMMISSION = 0.02

# Статусы заказа
ORDER_STATUS = {
    "0": "Создан",
    "1": "Оплачен",
    "2": "Выполнен",
    "3": "Отменён"
}