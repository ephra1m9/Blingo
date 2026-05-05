import os
import re


# Steam
STEAM_LOGIN_RE = re.compile(r'^[a-zA-Z0-9_]{2,32}$')

MIN_AMOUNT = 10
MAX_AMOUNT = 15_000
COMMISSION = 0.02

# Dessly
DESSLY_API_KEY = os.getenv("DESSLY_API_KEY")

# FreeKassa
FREEKASSA_SHOP_ID = os.getenv("FREEKASSA_SHOP_ID")
FREEKASSA_SECRET1 = os.getenv("FREEKASSA_SECRET1")   # для создания ссылки оплаты
FREEKASSA_SECRET2 = os.getenv("FREEKASSA_SECRET2")   # для проверки IPN-уведомлений

# Webhook
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))
