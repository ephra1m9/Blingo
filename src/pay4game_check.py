import json
import logging
import aiohttp

from .config import PAYFORGAME_API_KEY


logger = logging.getLogger(__name__)

PAY4GAME_STEAM_CHECK_URL = "https://pay4game.ru/api/v2/steam/topup/check"

# Минимальная сумма для проверки по документации Pay4Game
_CHECK_AMOUNT = 20


async def check_steam_login(username: str) -> dict:
    """
    Проверяет возможность пополнения Steam-аккаунта через Pay4Game API.

    Args:
        username: Логин Steam пользователя.

    Returns:
        {"can_refill": True}  — аккаунт найден и доступен для пополнения.
        {"can_refill": False} — аккаунт не найден или недоступен.
        {"error": True}       — сетевая ошибка или API недоступен.
    """
    params = {
        "account": username,
        "amount": _CHECK_AMOUNT,
    }
    headers = {
        "Authorization": f"Bearer {PAYFORGAME_API_KEY}",
        "Accept": "application/json",
    }

    logger.info(f"Проверка Steam логина через Pay4Game: username={username}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                PAY4GAME_STEAM_CHECK_URL,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                raw_text = await resp.text()
                logger.info(f"Ответ check (HTTP {resp.status}): {raw_text[:300]}")

                try:
                    data = json.loads(raw_text)
                except Exception as e:
                    logger.error(f"check_steam_login: не JSON ответ: {e} | raw={raw_text[:200]}")
                    return {"error": True}

                if resp.status == 401 or resp.status == 403:
                    logger.error(f"check_steam_login: ошибка авторизации HTTP {resp.status}")
                    return {"error": True}

                # Код 0 — успех, аккаунт найден
                status_code = data.get("status")
                try:
                    status_int = int(status_code)
                except (TypeError, ValueError):
                    logger.warning(f"check_steam_login: неожиданный статус={status_code} для username={username}")
                    return {"error": True}

                if status_int == 0:
                    return {"can_refill": True}
                elif status_int == -110:
                    # Account not found
                    logger.info(f"check_steam_login: аккаунт не найден username={username}")
                    return {"can_refill": False}
                elif status_int == -999:
                    # Other error — временная ошибка сервиса, пропускаем проверку
                    logger.warning(f"check_steam_login: временная ошибка сервиса (-999) для username={username}")
                    return {"error": True}
                else:
                    logger.warning(f"check_steam_login: статус={status_int} для username={username}")
                    return {"can_refill": False}

    except aiohttp.ClientError as e:
        logger.error(f"Сетевая ошибка check_steam_login для username={username}: {e}")
        return {"error": True}
    except Exception as e:
        logger.error(f"Неожиданная ошибка check_steam_login для username={username}: {e}")
        return {"error": True}
