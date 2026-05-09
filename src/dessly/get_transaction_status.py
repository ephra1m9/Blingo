import json
import logging
import aiohttp

from ..config import DESSLY_API_KEY


logger = logging.getLogger(__name__)

DESSLY_GET_URL = "https://desslyhub.com/api/v1/merchants/transaction/{transaction_id}"

# Коды статусов заказа Dessly
DESSLY_STATUSES = {
    "pending":    "Ожидает обработки",
    "processing": "Обрабатывается",
    "completed":  "Выполнен",
    "success":    "Выполнен",
    "failed":     "Ошибка выполнения",
    "canceled":   "Отменён",
}


def get_status_label(status: str) -> str:
    """Возвращает читаемое название статуса заказа Dessly."""
    return DESSLY_STATUSES.get(status, f"Статус: {status}")


async def get_dessly_transaction(transaction_id: str) -> dict:
    """
    Получить информацию о транзакции Dessly по ID.

    Args:
        transaction_id: ID транзакции в системе Dessly.

    Returns:
        dict с полями transaction_id, status, amount и др.
        При ошибке возвращает пустой dict {}.
    """
    url = DESSLY_GET_URL.format(transaction_id=transaction_id)
    headers = {
        "apikey": DESSLY_API_KEY,
        "Accept": "application/json",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                raw_text = await resp.text()
                try:
                    data = json.loads(raw_text)
                except json.JSONDecodeError as e:
                    logger.error(f"Dessly вернул не JSON для транзакции {transaction_id}: {e}")
                    return {}
                if resp.status != 200:
                    logger.error(
                        f"Dessly GET transaction {transaction_id}: HTTP {resp.status}, body={raw_text[:200]}"
                    )
                    return {}
                return data
    except aiohttp.ClientError as e:
        logger.error(f"Сетевая ошибка при получении транзакции Dessly {transaction_id}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Неожиданная ошибка при получении транзакции Dessly {transaction_id}: {e}")
        return {}
