import hashlib
import logging

from aiohttp import web
from aiogram import Bot

from .dessly.steam_transactions import get_usd_rate, rub_to_usd, steam_topup, is_success, get_status_label
from .order_storage import order_storage
from .config import FREEKASSA_SECRET2, FREEKASSA_SHOP_ID


logger = logging.getLogger(__name__)


def create_webhook_app(bot: Bot) -> web.Application:
    """
    Создаёт aiohttp-приложение для обработки IPN-уведомлений от FreeKassa.

    Args:
        bot: Экземпляр aiogram Bot для отправки уведомлений пользователям.

    Returns:
        Настроенное aiohttp web.Application.
    """
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/webhook/freekassa", handle_freekassa_ipn)
    return app


def _verify_sign(shop_id: str, amount: str, order_id: str, secret2: str, received_sign: str) -> bool:
    """
    Проверяет подпись IPN-уведомления от FreeKassa.
    Актуальный формат: MD5(shop_id:amount:secret2:order_id)
    """
    raw = f"{shop_id}:{amount}:{secret2}:{order_id}"
    expected = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return expected == received_sign


async def handle_freekassa_ipn(request: web.Request) -> web.Response:
    """
    Обрабатывает IPN-уведомление от FreeKassa об успешной оплате.

    FreeKassa отправляет POST с параметрами:
        MERCHANT_ID        — ID магазина
        AMOUNT             — сумма платежа
        MERCHANT_ORDER_ID  — числовой order_id и�� нашего хранилища
        SIGN               — подпись MD5(MERCHANT_ID:AMOUNT:SECRET2:MERCHANT_ORDER_ID)
        intid              — внутренний ID транзакции FreeKassa
        P_EMAIL            — email плательщика (опционально)
        CUR_ID             — вал��та
    """
    bot: Bot = request.app["bot"]

    try:
        data = await request.post()
    except Exception as e:
        logger.error(f"Ошибка чтения IPN от FreeKassa: {e}")
        return web.Response(status=400, text="Bad Request")

    shop_id = data.get("MERCHANT_ID", "")
    amount = data.get("AMOUNT", "")
    order_id_str = data.get("MERCHANT_ORDER_ID", "")
    received_sign = data.get("SIGN", "")

    logger.info(
        f"IPN FreeKassa: shop_id={shop_id}, amount={amount}, "
        f"order_id={order_id_str}, sign={received_sign}"
    )

    # Проверяем подпись
    if not _verify_sign(shop_id, amount, order_id_str, FREEKASSA_SECRET2, received_sign):
        logger.warning(f"Неверная подпись IPN FreeKassa: order_id={order_id_str}")
        return web.Response(status=403, text="Invalid sign")

    # Получаем данные заказа из хранилища
    try:
        order_id = int(order_id_str)
    except ValueError:
        logger.error(f"Неверный формат order_id: {order_id_str}")
        return web.Response(status=200, text="YES")

    order = order_storage.get(order_id)
    if order is None:
        logger.error(f"Заказ не найден или истёк: order_id={order_id}")
        return web.Response(status=200, text="YES")

    steam_login = order.steam_login
    user_id = order.user_id
    amount_rub = order.amount_rub

    logger.info(
        f"Обработка оплаты: user_id={user_id}, steam={steam_login}, amount_rub={amount_rub}"
    )

    # Уведомляем пользователя о начале обработки
    try:
        await bot.send_message(
            user_id,
            "⏳ Оплата получена! Пополняем баланс Steam...",
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

    # Конвертируем RUB → USD через курс ЦБ РФ
    try:
        usd_rate = await get_usd_rate()
        amount_usd = rub_to_usd(amount_rub, usd_rate)
        logger.info(f"Конвертация: {amount_rub} RUB → {amount_usd} USD (курс {usd_rate})")
    except Exception as e:
        logger.error(f"Ошибка получения курса ЦБ РФ: {e}")
        await _notify_error(bot, user_id, "Не удалось получить курс валют. Обратитесь в поддержку.")
        return web.Response(status=200, text="YES")

    # Создаём заказ на пополнение Steam через Dessly
    result = await steam_topup(username=steam_login, amount_usd=amount_usd)

    status = result.get("status", "error")
    order_dessly_id = result.get("order_id", "—")

    if is_success(result):
        status_label = get_status_label(status)
        # Удаляем заказ из хранилища после успешной обработки
        order_storage.delete(order_id)
        try:
            await bot.send_message(
                user_id,
                f"✅ <b>Пополнение Steam отправлено!</b>\n\n"
                f"🎮 Логин: <code>{steam_login}</code>\n"
                f"💰 Сумма: <b>{amount_rub} руб.</b> (~{amount_usd} USD)\n"
                f"🔖 ID заказа: <code>{order_dessly_id}</code>\n"
                f"📋 Статус: {status_label}\n\n"
                f"Средства поступят на счёт в течение ��ескольких минут.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление об успехе пользователю {user_id}: {e}")
    else:
        error_detail = result.get("error", "Неизвестная ошибка")
        logger.error(
            f"Ошибка Dessly: status={status}, error={error_detail}, "
            f"user_id={user_id}, steam={steam_login}"
        )
        await _notify_error(
            bot,
            user_id,
            f"Ошибка пополнения Steam: {error_detail}\n"
            f"Обратитесь в поддержку с логином <code>{steam_login}</code>.",
        )

    # FreeKassa требует ответ "YES" для подтверждения получения уведомления
    return web.Response(status=200, text="YES")


async def _notify_error(bot: Bot, user_id: int, message: str) -> None:
    """Отправляет пользователю сообщение об ошибке."""
    try:
        await bot.send_message(
            user_id,
            f"❌ <b>Ошибка!</b>\n\n{message}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить сообщение об ошибке пользователю {user_id}: {e}")
