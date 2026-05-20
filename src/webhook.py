import hmac
import hashlib
import json
import logging

from aiohttp import web
from aiogram import Bot

from .db.db_helper import (
    get_order,
    update_order_after_payment,
    update_steam_status,
    get_order_by_agent_transaction_id,
    get_payment_message_id,
)
from .config import COMMISSION, PAYFORGAME_SECRET, BOT_SECRET_KEY, STEAM_STATUS_LABELS
from .webhook_throttling import WebhookThrottlingMiddleware


logger = logging.getLogger(__name__)


async def _safe_delete_message(bot: Bot, chat_id: int, message_id: int) -> None:
    """Безопасно удаляет сообщение, игнорируя ошибки."""
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.debug(f"Не удалось удалить сообщение {message_id} в чате {chat_id}: {e}")

# Экземпляр throttling-middleware для вебхука:
# не более 10 запросов с одного IP за 60 секунд
_webhook_throttler = WebhookThrottlingMiddleware(max_calls=10, window_seconds=60.0)


def create_webhook_app(bot: Bot) -> web.Application:
    """
    Создаёт aiohttp-приложение для обработки вебхуков от Pay4Game
    и API-запросов от сайта.

    Args:
        bot: Экземпляр aiogram Bot для отправки уведомлений пользователям.

    Returns:
        Настроенное aiohttp web.Application с Rate Limiting middleware.
    """
    app = web.Application(middlewares=[_webhook_throttler.middleware])
    app["bot"] = bot
    app.router.add_post("/webhook/pay4game", handle_pay4game_webhook)
    app.router.add_post("/src/api/bot_steam_status.php", handle_site_status_request)
    return app


def _verify_signature(raw_body: bytes, secret: str, received_sign: str) -> bool:
    """
    Проверяет HMAC-SHA256 подпись вебхука от Pay4Game.
    Подпись вычисляется от сырого тела запроса.
    """
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received_sign)


async def handle_pay4game_webhook(request: web.Request) -> web.Response:
    """
    Обрабатывает вебхуки от Pay4Game.

    Типы вебхуков:
        status       — результат проведения платежа
        status_steam — результат пополнения Steam
    """
    bot: Bot = request.app["bot"]

    # Читаем сырое тело для верификации подписи
    try:
        raw_body = await request.read()
    except Exception as e:
        logger.error(f"Ошибка чтения тела вебхука Pay4Game: {e}")
        return web.Response(status=400, text="Bad Request")

    # Верифицируем подпись
    received_sign = request.headers.get("X-REQUEST-SIGNATURE", "")
    if not PAYFORGAME_SECRET:
        logger.error("PAYFORGAME_SECRET не задан — верификация невозможна")
        return web.Response(status=500, text="Server Error")

    if not _verify_signature(raw_body, PAYFORGAME_SECRET, received_sign):
        logger.warning(f"Неверная подпись вебхука Pay4Game: sign={received_sign[:20]}...")
        return web.Response(status=403, text="Invalid signature")

    # Парсим JSON
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError as e:
        logger.error(f"Вебхук Pay4Game: не JSON: {e} | raw={raw_body[:200]}")
        return web.Response(status=400, text="Bad Request")

    webhook_type = data.get("type", "")
    logger.info(f"Вебхук Pay4Game type={webhook_type}: {json.dumps(data)[:300]}")

    if webhook_type == "status":
        await _handle_status_webhook(bot, data)
    elif webhook_type == "status_steam":
        await _handle_status_steam_webhook(bot, data)
    else:
        logger.info(f"Вебхук Pay4Game: неизвестный тип '{webhook_type}', игнорируем")

    return web.Response(status=200, text="OK")


async def _handle_status_webhook(bot: Bot, data: dict) -> None:
    """
    Обрабатывает вебхук type=status — результат проведения платежа.
    Выдаёт заказ только при status=success и hold=0.
    """
    invoice_id: str = data.get("invoice_id", "")
    status: str = data.get("status", "")
    hold: int = int(data.get("hold", 1))
    amount = data.get("amount")

    logger.info(f"status webhook: invoice_id={invoice_id}, status={status}, hold={hold}")

    # invoice_id совпадает с order_id (формат "b_{случайные_символы}")
    order_id = invoice_id

    if status == "success" and hold == 1:
        logger.info(
            f"status webhook: платёж hold=1 для order_id={order_id}, "
            f"ожидаем повторный вебхук после проверки администратором"
        )
        return

    if status != "success":
        logger.info(f"status webhook: статус '{status}' для order_id={order_id}, пропускаем")
        return

    # status=success, hold=0 — обрабатываем платёж
    order = await get_order(order_id)
    if order is None:
        logger.error(f"status webhook: заказ не найден в БД: order_id={order_id}")
        return

    # Защита от дублирующих вебхуков
    if order.status != "Создан":
        logger.warning(
            f"status webhook: дубликат для order_id={order_id}, "
            f"статус уже '{order.status}', пропускаем"
        )
        return

    user_id = order.user_id
    steam_login = order.steam_login
    amount_rub = order.amount

    # Обновляем статус заказа в БД
    await update_order_after_payment(order_id, status=1)

    # Удаляем сообщение с кнопками оплаты
    payment_msg_id = await get_payment_message_id(order_id)
    if payment_msg_id:
        await _safe_delete_message(bot, user_id, payment_msg_id)

    # Уведомляем пользователя
    try:
        await bot.send_message(
            user_id,
            f"✅ <b>Оплата получена!</b>\n\n"
            f"🎮 Логин Steam: <code>{steam_login}</code>\n"
            f"💰 Сумма пополнения: <b>{amount_rub} руб.</b>\n\n"
            f"Пополнение баланса Steam выполняется автоматически.\n"
            f"Средства поступят на счёт в течение нескольких минут.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить уведомление об оплате пользователю {user_id}: {e}")


async def _handle_status_steam_webhook(bot: Bot, data: dict) -> None:
    """Обрабатывает вебхук type=status_steam — результат пополнения Steam. Сохраняет steam_status в БД и уведомляет пользователя."""
    agent_transaction_id: str = data.get("agent_transaction_id", "")
    steam_status: str = data.get("status", "")
    steam_account: str = data.get("steam_account", "")
    steam_amount = data.get("steam_amount", "")
    invoice_id: str = data.get("invoice_id", "")

    logger.info(
        f"status_steam webhook: agent_transaction_id={agent_transaction_id}, "
        f"status={steam_status}, account={steam_account}"
    )

    if not agent_transaction_id:
        logger.warning("status_steam webhook: отсутствует agent_transaction_id")
        return

    await update_steam_status(agent_transaction_id, steam_status)

    order = await get_order_by_agent_transaction_id(agent_transaction_id)
    if order is None:
        logger.warning(f"status_steam webhook: заказ не найден для agent_transaction_id={agent_transaction_id}")
        return

    user_id = order.user_id
    status_label = STEAM_STATUS_LABELS.get(steam_status, f"Статус: {steam_status}")

    payment_msg_id = await get_payment_message_id(order.order_id)
    if payment_msg_id:
        await _safe_delete_message(bot, user_id, payment_msg_id)

    if steam_status == "success":
        try:
            await bot.send_message(
                user_id,
                f"🎮 <b>Баланс Steam пополнен!</b>\n\n"
                f"👤 Аккаунт: <code>{steam_account or order.steam_login}</code>\n"
                f"💰 Сумма: <b>{steam_amount or order.amount} руб.</b>\n"
                f"📋 Статус: {status_label}",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление о пополнении Steam пользователю {user_id}: {e}")
    elif steam_status == "error":
        try:
            await bot.send_message(
                user_id,
                f"❌ <b>Ошибка пополнения Steam</b>\n\n"
                f"👤 Аккаунт: <code>{steam_account or order.steam_login}</code>\n"
                f"📋 Статус: {status_label}\n\n"
                f"Обратитесь в поддержку.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление об ошибке Steam пользователю {user_id}: {e}")


async def handle_site_status_request(request: web.Request) -> web.Response:
    """Обрабатывает запрос от сайта kazna.shop на получение статуса транзакции.
    Запрос:
        POST /src/api/bot_steam_status.php
        {"bot_token": "...", "agent_transaction_id": "..."}
    Ответ при успехе:
        {"found": true, "steam_account": "...", "steam_amount": 500,
         "steam_status": "success", "status": "Оплачен"}
    Ответ при ненайденном заказе:
        {"found": false}"""
    try:
        data = await request.json()
    except Exception as e:
        logger.warning(f"bot_steam_status: ошибка чтения JSON: {e}")
        return web.json_response({"error": "Bad Request"}, status=400)

    # Проверка токена
    bot_token = data.get("bot_token", "")
    if not BOT_SECRET_KEY or bot_token != BOT_SECRET_KEY:
        logger.warning("bot_steam_status: неверный bot_token")
        return web.json_response({"error": "Unauthorized"}, status=401)

    agent_transaction_id = data.get("agent_transaction_id", "")
    if not agent_transaction_id:
        return web.json_response({"error": "agent_transaction_id required"}, status=400)

    order = await get_order_by_agent_transaction_id(agent_transaction_id)
    if order is None:
        logger.info(f"bot_steam_status: заказ не найден для agent_transaction_id={agent_transaction_id}")
        return web.json_response({"found": False})

    return web.json_response({
        "found": True,
        "steam_account": order.steam_login,
        "steam_amount": order.amount,
        "steam_status": order.steam_status or "pending",
        "status": order.status,
    })
