import asyncio
import json
import logging
import aiohttp

from .config import BOT_SECRET_KEY

logger = logging.getLogger(__name__)


async def _safe_delete_message(bot, chat_id: int, message_id: int) -> None:
    """Безопасно удаляет сообщение, игнорируя ошибки."""
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.debug(f"Не удалось удалить сообщение {message_id} в чате {chat_id}: {e}")

SITE_STATUS_URL = "https://kazna.shop/src/api/bot_steam_status.php"

# Интервал между запросами в секундах
POLL_INTERVAL = 10
# Максимальное время ожидания в секундах (15 минут)
POLL_TIMEOUT = 900
# Финальные статусы пополнения Steam
FINAL_STEAM_STATUSES = {"success", "error"}
# Финальные статусы оплаты
FINAL_PAYMENT_STATUSES = {"Оплачен", "Отменён"}

# Словарь активных задач поллинга: order_id -> asyncio.Task
_active_polling_tasks: dict[str, asyncio.Task] = {}


def cancel_polling(order_id: str) -> bool:
    """Отменяет фоновую задачу поллинга для указанного заказа."""
    task = _active_polling_tasks.pop(order_id, None)
    if task and not task.done():
        task.cancel()
        logger.info(f"Поллинг order_id={order_id}: задача отменена принудительно")
        return True
    return False


async def poll_payment_status(agent_transaction_id: str) -> dict | None:
    """Однократно запрашивает статус платежа у сайта."""
    payload = {
        "bot_token": BOT_SECRET_KEY,
        "agent_transaction_id": agent_transaction_id,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                SITE_STATUS_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                raw = await resp.text()
                logger.debug(f"poll_payment_status (HTTP {resp.status}): {raw[:300]}")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    logger.error(f"poll_payment_status: не JSON: {raw[:200]}")
                    return None
    except Exception as e:
        logger.warning(f"poll_payment_status: ошибка сети для {agent_transaction_id}: {e}")
        return None


async def wait_for_payment_and_notify(bot, user_id: int, agent_transaction_id: str, order_id: str,) -> None:
    """Фоновая задача: опрашивает сайт до получения финального статуса платежа, затем уведомляет пользователя в Telegram."""
    from .db.db_helper import update_order_after_payment, update_steam_status, get_order, get_payment_message_id

    # Регистрируем задачу в словаре активных поллингов
    current_task = asyncio.current_task()
    if current_task:
        _active_polling_tasks[order_id] = current_task

    logger.info(
        f"Запуск поллинга: order_id={order_id}, "
        f"agent_transaction_id={agent_transaction_id}, user_id={user_id}"
    )

    elapsed = 0
    payment_status = ""
    steam_status = ""

    try:
        while elapsed < POLL_TIMEOUT:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

            # Проверяем, не отменён ли заказ локально (пользователь нажал «Отменить платёж»)
            order = await get_order(order_id)
            if order and order.status == "Отменён":
                logger.info(f"Поллинг order_id={order_id}: заказ отменён локально, завершаем")
                return

            data = await poll_payment_status(agent_transaction_id)

            if data is None:
                logger.warning(f"Поллинг order_id={order_id}: нет ответа от сайта, повтор через {POLL_INTERVAL}с")
                continue

            if not data.get("found"):
                logger.info(f"Поллинг order_id={order_id}: запись ещё не найдена на сайте, повтор")
                continue

            payment_status = data.get("status", "")
            steam_status = data.get("steam_status", "")
            steam_account = data.get("steam_account", "")
            steam_amount = data.get("steam_amount", "")

            logger.info(
                f"Поллинг order_id={order_id}: payment_status={payment_status}, "
                f"steam_status={steam_status}"
            )

            # Обновляем статус оплаты в БД если оплачен
            if payment_status == "Оплачен":
                await update_order_after_payment(order_id, status=1)

            # Обновляем steam_status в БД
            if steam_status:
                await update_steam_status(agent_transaction_id, steam_status)

            # Проверяем финальный статус пополнения Steam
            if steam_status in FINAL_STEAM_STATUSES:
                # Удаляем сообщение с кнопками оплаты
                payment_msg_id = await get_payment_message_id(order_id)
                if payment_msg_id:
                    await _safe_delete_message(bot, user_id, payment_msg_id)

                if steam_status == "success":
                    try:
                        await bot.send_message(
                            user_id,
                            f"✅ <b>Оплата получена и баланс Steam пополнен!</b>\n\n"
                            f"🎮 Аккаунт: <code>{steam_account}</code>\n"
                            f"💰 Сумма пополнения: <b>{steam_amount} руб.</b>",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось уведомить пользователя {user_id}: {e}")
                else:
                    # steam_status == "error"
                    try:
                        await bot.send_message(
                            user_id,
                            f"❌ <b>Ошибка пополнения Steam</b>\n\n"
                            f"🎮 Аккаунт: <code>{steam_account}</code>\n\n"
                            f"Обратитесь в поддержку.",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось уведомить пользователя {user_id}: {e}")
                logger.info(f"Поллинг order_id={order_id}: завершён со статусом steam_status={steam_status}")
                return

            # Если оплата прошла, но steam_status ещё pending — продолжаем ждать
            if payment_status == "Оплачен" and steam_status in ("pending", ""):
                logger.info(f"Поллинг order_id={order_id}: оплачен, ждём пополнения Steam...")
                continue

            # Если статус оплаты финальный, но не "Оплачен" — завершаем
            if payment_status in FINAL_PAYMENT_STATUSES and payment_status != "Оплачен":
                logger.info(f"Поллинг order_id={order_id}: платёж в статусе '{payment_status}', завершаем")
                return

        # Таймаут
        logger.warning(
            f"Поллинг order_id={order_id}: таймаут {POLL_TIMEOUT}с, "
            f"последний статус: payment={payment_status}, steam={steam_status}"
        )
        # Удаляем сообщение с кнопками оплаты
        payment_msg_id = await get_payment_message_id(order_id)
        if payment_msg_id:
            await _safe_delete_message(bot, user_id, payment_msg_id)

        try:
            await bot.send_message(
                user_id,
                "⚠️ <b>Время ожидания истекло.</b>\n\n"
                "Если вы оплатили заказ, но баланс не пополнился — обратитесь в поддержку.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение о таймауте пользователю {user_id}: {e}")

    except asyncio.CancelledError:
        logger.info(f"Поллинг order_id={order_id}: задача отменена (CancelledError)")
        raise
    finally:
        # Удаляем задачу из словаря при любом завершении
        _active_polling_tasks.pop(order_id, None)
