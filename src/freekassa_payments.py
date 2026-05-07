import hashlib
import logging

from .config import FREEKASSA_SHOP_ID, FREEKASSA_SECRET1, COMMISSION
from .db.db_helper import create_order


logger = logging.getLogger(__name__)

FREEKASSA_PAY_URL = "https://pay.fk.money/"


def _make_sign(shop_id: str, amount: str, secret: str, currency: str, order_id: str) -> str:
    """
    Формирует MD5-подпись для платёжной формы FreeKassa.
    Формат (раздел 1.5 документации): MD5(shop_id:amount:secret:currency:order_id)
    Пример из документации: md5('7012:100.11:secret:RUB:154')
    """
    raw = f"{shop_id}:{amount}:{secret}:{currency}:{order_id}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


async def create_payment_url(amount_rub: int, steam_login: str, user_id: int) -> tuple[str, int]:
    """
    Создаёт заказ в БД и формирует ссылку на страницу оплаты FreeKassa.

    Args:
        amount_rub: Сумма пополнения Steam в рублях (без комиссии).
        steam_login: Логин Steam пользователя.
        user_id: Telegram user_id для уведомления после оплаты.

    Returns:
        Кортеж (payment_url, order_id).
    """
    total_rub = round(amount_rub * (1 + COMMISSION))

    # Сохраняем заказ в БД, получаем числовой ID
    order_id = await create_order(
        user_id=user_id,
        steam_login=steam_login,
        amount=amount_rub,
    )

    amount_str = str(total_rub)
    currency = "RUB"
    order_id_str = str(order_id)

    sign = _make_sign(
        shop_id=FREEKASSA_SHOP_ID,
        amount=amount_str,
        secret=FREEKASSA_SECRET1,
        currency=currency,
        order_id=order_id_str,
    )

    params = (
        f"?m={FREEKASSA_SHOP_ID}"
        f"&oa={amount_str}"
        f"&currency=RUB"
        f"&o={order_id_str}"
        f"&s={sign}"
        f"&lang=ru"
    )

    payment_url = FREEKASSA_PAY_URL + params

    logger.info(
        f"Создана ссылка FreeKassa: order_id={order_id}, "
        f"user_id={user_id}, steam={steam_login}, total={total_rub} руб."
    )

    return payment_url, order_id
