import os
import hashlib
import logging

from aiohttp import web
from aiogram import Bot

from .dessly.steam_top_up import get_usd_rate, rub_to_usd, steam_topup, is_success
from .dessly.get_transaction_status import get_status_label
from .db.db_helper import get_order, update_order_after_payment
from .config import COMMISSION
from .webhook_throttling import WebhookThrottlingMiddleware


logger = logging.getLogger(__name__)

FREEKASSA_SECRET2 = os.getenv("FREEKASSA_SECRET2")

# Экземпляр throttling-middleware для вебхука:
# не более 10 запросов с одного IP за 60 секунд
_webhook_throttler = WebhookThrottlingMiddleware(max_calls=10, window_seconds=60.0)


def create_webhook_app(bot: Bot) -> web.Application:
    """
    Создаёт aiohttp-приложение для обработки IPN-уведомлений от FreeKassa.

    Args:
        bot: Экземпляр aiogram Bot для отправки уведомлений пользователям.

    Returns:
        Настроенное aiohttp web.Application с Rate Limiting middleware.
    """
    app = web.Application(middlewares=[_webhook_throttler.middleware])
    app["bot"] = bot
    app.router.add_post("/webhook/freekassa", handle_freekassa_ipn)
    return app


def _verify_sign(shop_id: str, amount: str, order_id: str, secret2: str, received_sign: str) -> bool:
    """
    Проверяет подпись IPN-уведомления от FreeKassa.
    Формат: MD5(shop_id:amount:secret2:order_id)
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
        MERCHANT_ORDER_ID  — числовой order_id из таблицы orders_history
        SIGN               — подпись MD5(MERCHANT_ID:AMOUNT:SECRET2:MERCHANT_ORDER_ID)
        intid              — внутренний ID транзакции FreeKassa
        P_EMAIL            — email плательщика (опционально)
        CUR_ID             — валюта
    """
    bot: Bot = request.app["bot"]

    try:
        data = await request.post()
    except Exception as e:
        logger.error(f"Ошибка чтения IPN от FreeKassa: {e}")
        return web.Response(status=400, text="Bad Request")

    # Логируем ВСЕ параметры для отладки
    logger.info(f"IPN FreeKassa RAW params: {dict(data)}")

    # FreeKassa отправляет status_check=1 для проверки доступности URL
    if data.get("status_check") == "1":
        logger.info("FreeKassa status_check: отвечаем YES")
        return web.Response(status=200, text="YES")

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

    # Получаем данные заказа из БД
    try:
        order_id = int(order_id_str)
    except ValueError:
        logger.error(f"Неверный формат order_id: {order_id_str}")
        return web.Response(status=200, text="YES")

    order = await get_order(order_id)
    if order is None:
        logger.error(f"Заказ не найден в БД: order_id={order_id}")
        return web.Response(status=200, text="YES")

    # --- Защита от Race Condition (дублирующих IPN) ---
    # FreeKassa может повторно отправить IPN при таймауте.
    # Обрабатываем заказ только если он ещё в статусе "Создан".
    if order.status != "Создан":
        logger.warning(
            f"IPN дубликат или повтор: order_id={order_id} уже в статусе '{order.status}'. "
            f"Пропускаем вызов Dessly."
        )
        return web.Response(status=200, text="YES")

    steam_login = order.steam_login
    user_id = order.user_id
    amount_rub = order.amount

    # --- Сверка суммы из IPN с ожидаемой суммой из БД ---
    # Ожидаемая сумма к оплате = сумма пополнения + комиссия
    expected_amount = round(amount_rub * (1 + COMMISSION / 100), 2)
    try:
        ipn_amount = round(float(amount), 2)
    except (ValueError, TypeError):
        logger.error(f"Некорректный формат суммы в IPN: amount='{amount}', order_id={order_id}")
        return web.Response(status=200, text="YES")

    if abs(ipn_amount - expected_amount) > 0.01:
        logger.error(
            f"Несоответствие суммы IPN: получено {ipn_amount}, "
            f"ожидалось {expected_amount} (order_id={order_id}, amount_rub={amount_rub})"
        )
        # Не отменяем заказ — возможно, ошибка округления на стороне FreeKassa.
        # Логируем для ручной проверки, но продолжаем обработку.
        # Если хотите жёсткую блокировку — раскомментируйте строки ниже:
        # await _notify_error(bot, user_id, "Ошибка проверки суммы платежа. Обратитесь в поддержку.")
        # return web.Response(status=200, text="YES")

    logger.info(
        f"Обработка оплаты: user_id={user_id}, steam_login=***{steam_login[-3:]}, "
        f"amount_rub={amount_rub}, ipn_amount={ipn_amount}"
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
        await update_order_after_payment(order_id, status=3)
        await _notify_error(bot, user_id, "Не удалось получить курс валют. Обратитесь в поддержку.")
        return web.Response(status=200, text="YES")

    # Создаём заказ на пополнение Steam через Dessly
    result = await steam_topup(
        username=steam_login,
        amount_usd=amount_usd,
        reference=str(order_id),
    )

    status = result.get("status", "error")
    transaction_id = result.get("transaction_id")

    if is_success(result):
        # Сохраняем статус "Оплачен" и transaction_id Dessly в БД
        await update_order_after_payment(
            order_id,
            status=1,
            dessly_order_id=str(transaction_id) if transaction_id is not None else None,
        )

        status_label = get_status_label(status)
        try:
            await bot.send_message(
                user_id,
                f"✅ <b>Заявка на пополнение отправлена!</b>\n\n"
                f"🎮 Логин: <code>{steam_login}</code>\n"
                f"💰 Сумма: <b>{amount_rub} руб.</b> (~{amount_usd} USD)\n"
                f"🔖 ID транзакции: <code>{transaction_id or '—'}</code>\n"
                f"📋 Статус: {status_label}\n\n"
                f"Средства поступят на счёт в течение нескольких минут.",
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
        # Сохраняем статус "Отменён" в БД
        await update_order_after_payment(order_id, status=3)
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
