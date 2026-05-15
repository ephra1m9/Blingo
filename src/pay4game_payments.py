import hmac
import hashlib
import json
import logging
import secrets
import string
import aiohttp

from .config import COMMISSION, PAYFORGAME_API_KEY, PAYFORGAME_SECRET, PAY4GAME_RETURN_URL, BOT_SECRET_KEY
from .db.db_helper import create_order, update_order_agent_transaction_id


logger = logging.getLogger(__name__)

PAY4GAME_CREATE_URL = "https://pay4game.ru/api/v1/payment/create"
SITE_REGISTER_URL = "https://kazna.shop/src/api/bot_steam_register.php"

# Максимальное количество попыток генерации order_id при коллизии в БД
MAX_ORDER_ID_RETRIES = 3
# Алфавит для генерации случайной части order_id
_ORDER_ID_ALPHABET = string.ascii_letters + string.digits


def _generate_order_id() -> str:
    """
    Генерирует уникальный order_id формата b_{8 случайных букв/цифр}.

    Использует secrets.choice (криптографически безопасный рандом).
    Алфавит: a-z, A-Z, 0-9 (62 символа). Пространство: 62^8 ≈ 218 триллионов комбинаций.
    """
    suffix = ''.join(secrets.choice(_ORDER_ID_ALPHABET) for _ in range(8))
    return f"b_{suffix}"


def _make_signature(invoice_id: str, amount: str, email: str, secret: str) -> str:
    """
    Формирует HMAC-SHA256 подпись для запроса к Pay4Game.
    Формат: HMAC-SHA256("{invoice_id}:{amount}:{email}", secret_key)
    """
    data = f"{invoice_id}:{amount}:{email}"
    return hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()


async def _register_on_site(
    invoice_id: str,
    agent_transaction_id: str,
    payment_id: str,
    user_id: int,
    steam_account: str,
    steam_amount: int,
    payment_amount: float,
) -> None:
    """
    Регистрирует платёж на сайте kazna.shop после успешного создания в Pay4Game.
    Ошибки не прерывают основной поток — только логируются.
    """
    payload = {
        "bot_token": BOT_SECRET_KEY,
        "invoice_id": invoice_id,
        "agent_transaction_id": agent_transaction_id,
        "payment_id": payment_id,
        "user_id": user_id,
        "steam_account": steam_account,
        "steam_amount": steam_amount,
        "payment_amount": payment_amount,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                SITE_REGISTER_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                raw = await resp.text()
                logger.info(f"Регистрация на сайте (HTTP {resp.status}): {raw[:200]}")
    except Exception as e:
        logger.warning(f"Не удалось зарегистрировать платёж на сайте: {e}")


async def create_payment_url(amount_rub: int, steam_login: str, user_id: int, method: str = "sbp") -> tuple[str, str]:
    """
    Создаёт заказ в БД, формирует платёж в Pay4Game и регистрирует его на сайте.

    Args:
        amount_rub: Сумма пополнения Steam в рублях (без комиссии).
        steam_login: Логин Steam пользователя.
        user_id: Telegram user_id для уведомления после оплаты.
        method: Способ оплаты (sbp, card, sberpay, tpay, cardkz, carduz, uzum).

    Returns:
        Кортеж (payment_url, order_id).
    """
    if not PAYFORGAME_API_KEY or not PAYFORGAME_SECRET:
        raise ValueError("PAYFORGAME_API_KEY или PAYFORGAME_SECRET не заданы в переменных окружения")

    # 1. Генерируем order_id и создаём заказ в БД (с retry на случай коллизии)
    for attempt in range(1, MAX_ORDER_ID_RETRIES + 1):
        order_id = _generate_order_id()
        db_order_id = await create_order(
            order_id=order_id,
            user_id=user_id,
            steam_login=steam_login,
            amount=amount_rub,
            method=method,
        )
        if db_order_id is not None:
            break
        logger.warning(
            f"Коллизия order_id={order_id} при вставке в БД, "
            f"попытка {attempt}/{MAX_ORDER_ID_RETRIES}"
        )
    else:
        raise RuntimeError(
            f"Не удалось создать заказ в БД после {MAX_ORDER_ID_RETRIES} попыток"
        )

    # 2. Формируем параметры платежа (invoice_id совпадает с order_id)
    invoice_id = order_id
    email = f"user_{user_id}@blingo.bot"
    amount_total = round(amount_rub * (1 + COMMISSION / 100), 2)
    amount_str = f"{amount_total:.2f}"

    # 3. Формируем подпись
    signature = _make_signature(invoice_id, amount_str, email, PAYFORGAME_SECRET)

    # 4. Формируем параметры запроса
    params = {
        "method": method,
        "invoice_id": invoice_id,
        "amount": amount_str,
        "email": email,
        "steam_account": steam_login,
        "steam_amount": str(amount_rub),
    }
    if PAY4GAME_RETURN_URL:
        params["return_url"] = PAY4GAME_RETURN_URL

    headers = {
        "Authorization": f"Bearer {PAYFORGAME_API_KEY}",
        "X-REQUEST-SIGNATURE": signature,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    logger.info(
        f"Создание платежа Pay4Game: invoice_id={invoice_id}, "
        f"user_id={user_id}, steam={steam_login}, amount_total={amount_total}"
    )

    # 5. Отправляем запрос в Pay4Game
    async with aiohttp.ClientSession() as session:
        async with session.post(
            PAY4GAME_CREATE_URL,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            raw_text = await resp.text()
            logger.info(f"Ответ Pay4Game (HTTP {resp.status}): {raw_text[:500]}")

            try:
                data = json.loads(raw_text)
            except Exception as e:
                logger.error(f"Pay4Game вернул не JSON: {e} | raw={raw_text[:200]}")
                raise RuntimeError(f"Некорректный ответ Pay4Game: {raw_text[:100]}")

            if resp.status != 200 or not data.get("success"):
                error_msg = data.get("message") or f"HTTP {resp.status}"
                logger.error(f"Ошибка создания платежа Pay4Game: {error_msg}")
                raise RuntimeError(f"Ошибка Pay4Game: {error_msg}")

    payment_url: str = data["url"]
    payment_uuid: str = data.get("uuid", "")
    agent_transaction_id: str = data.get("agent_transaction_id", "")

    # 6. Сохраняем agent_transaction_id в БД
    if agent_transaction_id:
        await update_order_agent_transaction_id(order_id, agent_transaction_id)

    # 7. Регистрируем платёж на сайте (не блокирует при ошибке)
    await _register_on_site(
        invoice_id=invoice_id,
        agent_transaction_id=agent_transaction_id,
        payment_id=payment_uuid,
        user_id=user_id,
        steam_account=steam_login,
        steam_amount=amount_rub,
        payment_amount=amount_total,
    )

    logger.info(
        f"Платёж создан: order_id={order_id}, invoice_id={invoice_id}, "
        f"uuid={payment_uuid}, agent_transaction_id={agent_transaction_id}"
    )

    return payment_url, order_id
