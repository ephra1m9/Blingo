import json
import logging
import aiohttp

from ..config import DESSLY_API_KEY


logger = logging.getLogger(__name__)

DESSLY_TOPUP_URL = "https://desslyhub.com/api/v1/service/steamtopup/topup"
DESSLY_CHECK_LOGIN_URL = "https://desslyhub.com/api/v1/service/steamtopup/check_login"
CBR_RATES_URL = "https://www.cbr-xml-daily.ru/daily_json.js"


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


async def steam_topup(username: str, amount_usd: float, reference: str | None = None) -> dict:
    """
    Создаёт заказ на пополнение Steam через Dessly API.

    Args:
        username: Логин Steam пользователя.
        amount_usd: Сумма пополнения в USD (от 0.1 до 1000).
        reference: Опциональный внешний ID заказа.

    Returns:
        dict с полями: transaction_id, status, error_code.
        При ошибке возвращает {"status": "error", "error": "описание"}.
    """
    payload: dict = {
        "username": username,
        "amount": amount_usd,
    }
    if reference is not None:
        payload["reference"] = reference

    body = json.dumps(payload, separators=(",", ":"))
    headers = {
        "apikey": DESSLY_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    logger.info(
        f"Отправка заказа в Dessly: username={username}, amount_usd={amount_usd}"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                DESSLY_TOPUP_URL,
                data=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                raw_text = await resp.text()
                logger.info(
                    f"Ответ Dessly (HTTP {resp.status}): {raw_text[:500]}"
                )

                try:
                    data = json.loads(raw_text)
                except json.JSONDecodeError as e:
                    logger.error(f"Dessly вернул не JSON ответ: {e} | raw={raw_text[:200]}")
                    return {"status": "error", "error": f"Некорректный ответ сервера: {raw_text[:100]}"}

                if resp.status != 200:
                    error_msg = (
                        data.get("detail")
                        or data.get("message")
                        or data.get("error")
                        or f"HTTP {resp.status} (error_code={data.get('error_code', '?')})"
                    )
                    return {"status": "error", "error": error_msg}

                # Проверяем error_code в теле ответа
                error_code = data.get("error_code", 0)
                if error_code != 0:
                    logger.error(f"Dessly вернул error_code={error_code}: {data}")
                    return {"status": "error", "error": f"Dessly error_code={error_code}"}

                return data

    except aiohttp.ClientError as e:
        logger.error(f"Сетевая ошибка при обращении к Dessly: {e}")
        return {"status": "error", "error": str(e)}
    except Exception as e:
        logger.error(f"Неожиданная ошибка Dessly: {e}")
        return {"status": "error", "error": str(e)}


def is_success(result: dict) -> bool:
    """Проверяет, успешно ли создан/обрабатывается заказ."""
    return result.get("status") in ("pending", "processing", "completed")


async def check_steam_login(username: str, amount: float = 1.0) -> dict:
    """
    Проверяет возможность пополнения Steam-аккаунта по логину через Dessly API.

    Args:
        username: Логин Steam пользователя.
        amount: Сумма в USD для проверки (по умолчанию 1.0).

    Returns:
        {"can_refill": True}  — аккаунт найден и доступен для пополнения.
        {"can_refill": False} — аккаунт не найден или недоступен.
        {"error": True}       — сетевая ошибка или API недоступен.
    """
    payload = {"username": username, "amount": amount}
    body = json.dumps(payload, separators=(",", ":"))
    headers = {
        "apikey": DESSLY_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    logger.info(f"Проверка Steam логина через Dessly: username={username}, amount={amount}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                DESSLY_CHECK_LOGIN_URL,
                data=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                raw_text = await resp.text()
                logger.info(f"Ответ check_login (HTTP {resp.status}): {raw_text[:500]}")

                try:
                    data = json.loads(raw_text)
                except json.JSONDecodeError as e:
                    logger.error(f"check_login: не JSON ответ: {e} | raw={raw_text[:200]}")
                    return {"error": True}

                error_code = data.get("error_code", 0)
                if error_code != 0:
                    logger.warning(f"check_login: error_code={error_code} для username={username}")
                    return {"can_refill": False}

                can_refill = str(data.get("can_refill", "false")).lower() == "true"
                return {"can_refill": can_refill}

    except aiohttp.ClientError as e:
        logger.error(f"Сетевая ошибка check_login для username={username}: {e}")
        return {"error": True}
    except Exception as e:
        logger.error(f"Неожиданная ошибка check_login для username={username}: {e}")
        return {"error": True}
