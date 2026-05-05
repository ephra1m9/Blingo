import json
import time
import hmac
import hashlib
import logging
import aiohttp

from ..config import DESSLY_API_KEY


logger = logging.getLogger(__name__)

DESSLY_ORDERS_URL = "https://desslyhub.com/api/v1/orders"
CBR_RATES_URL = "https://www.cbr-xml-daily.ru/daily_json.js"

# Коды статусов заказа Dessly
DESSLY_STATUSES = {
    "pending":   "Ожидает обработки",
    "paid":      "Оплачен",
    "executing": "Выполняется",
    "completed": "Выполнен",
    "failed":    "Ошибка выполнения",
    "canceled":  "Отменён",
}


def _make_signature(api_key: str, timestamp: str, body: str) -> str:
    """
    Формирует HMAC-SHA256 подпись для Dessly API.
    Формула: HMAC-SHA256(secret=DESSLY_API_KEY, message=apiKey+timestamp+body)
    Возвращает lowercase hex.
    """
    message = api_key + timestamp + body
    signature = hmac.new(
        DESSLY_API_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signature


def _build_headers(body: str) -> dict:
    """Формирует заголовки запроса к Dessly API с подписью."""
    timestamp = str(int(time.time()))
    signature = _make_signature(DESSLY_API_KEY, timestamp, body)
    return {
        "X-Api-Key": DESSLY_API_KEY,
        "X-Timestamp": timestamp,
        "X-Signature": signature,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def get_usd_rate() -> float:
    """Получает актуальный курс USD/RUB от ЦБ РФ."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            CBR_RATES_URL,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
            rate: float = data["Valute"]["USD"]["Value"]
            logger.info(f"Курс USD/RUB от ЦБ РФ: {rate}")
            return rate


def rub_to_usd(amount_rub: int | float, usd_rate: float) -> float:
    """Конвертирует рубли в доллары и округляет до 2 знаков."""
    return round(amount_rub / usd_rate, 2)


async def steam_topup(username: str, amount_usd: float) -> dict:
    """
    Создаёт заказ на пополнение Steam через новый Dessly API.

    Args:
        username: Логин Steam пользователя.
        amount_usd: Сумма пополнения в USD (от 0.1 до 1000).

    Returns:
        dict с ключами: order_id, status, total_amount_cents,
        final_amount_cents, commission_cents, created_at.
        При ошибке возвращает {"status": "error", "error": "описание"}.
    """
    service_params = json.dumps({"username": username, "amount": amount_usd})

    payload = {
        "method": "balance",
        "payment_params": None,
        "service_params": service_params,
        "service_type": "steam_refill",
    }

    body = json.dumps(payload, separators=(",", ":"))
    headers = _build_headers(body)

    logger.info(
        f"Отправка заказа в Dessly: username={username}, amount_usd={amount_usd}"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                DESSLY_ORDERS_URL,
                data=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json(content_type=None)
                logger.info(f"Ответ Dessly (статус HTTP {resp.status}): {data}")

                if resp.status != 200:
                    return {
                        "status": "error",
                        "error": data.get("detail") or data.get("message") or f"HTTP {resp.status}",
                    }

                return data

    except aiohttp.ClientError as e:
        logger.error(f"Сетевая ошибка при обращении к Dessly: {e}")
        return {"status": "error", "error": str(e)}
    except Exception as e:
        logger.error(f"Неожиданная ошибка Dessly: {e}")
        return {"status": "error", "error": str(e)}


def is_success(result: dict) -> bool:
    """Проверяет, успешно ли создан заказ."""
    return result.get("status") in ("pending", "paid", "executing", "completed")


def get_status_label(status: str) -> str:
    """Возвращает читаемое название статуса заказа."""
    return DESSLY_STATUSES.get(status, f"Статус: {status}")
