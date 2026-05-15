import logging

from sqlalchemy import select

from .db_connect import get_async_session
from .models import UserInfo, OrdersHistory
from ..config import ORDER_STATUS


async def get_or_create_user(user_id: int, user_name: str | None = None) -> tuple[UserInfo | None, bool]:
    """Найти или добавить пользователя в БД"""
    async with get_async_session() as session:
        user = await session.get(UserInfo, user_id)

        if not user:
            user = UserInfo(user_id=user_id, user_name=user_name)
            session.add(user)

            try:
                await session.commit()
                logging.info(f"В БД добавлен новый пользователь, ID: {user_id}")
                return user, True
            
            except Exception as e:
                await session.rollback()
                logging.error(f"Ошибка при добавлении пользователя в БД: {e}")
                return None, False
            
        return user, False
    

async def get_user_orders(user_id: int) -> list[OrdersHistory]:
    """Получить историю пополнений пользователя"""
    async with get_async_session() as session:
        try:
            result = await session.execute(
                select(OrdersHistory)
                .where(OrdersHistory.user_id == user_id)
                .order_by(OrdersHistory.created_at.desc())
                .limit(5)
            )

            orders = result.scalars().all()

            return list(orders)
        
        except Exception as e:
            logging.error(f"Ошибка при получении истории заказов: {e}")
            return []


async def create_order(order_id: str, user_id: int, steam_login: str, amount: int, pay_amount: float, method: str = "sbp") -> str | None:
    """Создать новый заказ с переданным order_id, вернуть order_id при успехе"""
    async with get_async_session() as session:
        try:
            order = OrdersHistory(
                order_id=order_id,
                user_id=user_id,
                steam_login=steam_login,
                amount=amount,
                pay_amount=pay_amount,
                method=method,
            )

            session.add(order)
            await session.commit()
            logging.info(f"Добавлен новый заказ #{order_id} на сумму {amount} руб.")
            return order_id

        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при создании заказа #{order_id}: {e}")
            return None


async def get_order(order_id: str) -> OrdersHistory | None:
    """Получить заказ из БД по order_id"""
    async with get_async_session() as session:
        try:
            order = await session.get(OrdersHistory, order_id)
            return order
        except Exception as e:
            logging.error(f"Ошибка при получении заказа #{order_id}: {e}")
            return None


async def get_order_by_agent_transaction_id(agent_transaction_id: str) -> OrdersHistory | None:
    """Получить заказ из БД по agent_transaction_id (ID транзакции Pay4Game)"""
    async with get_async_session() as session:
        try:
            result = await session.execute(
                select(OrdersHistory)
                .where(OrdersHistory.agent_transaction_id == agent_transaction_id)
            )
            return result.scalars().first()
        except Exception as e:
            logging.error(f"Ошибка при поиске заказа по agent_transaction_id={agent_transaction_id}: {e}")
            return None


async def change_order_status(order_id: str, status: int) -> bool:
    """Изменить статус заказа"""
    async with get_async_session() as session:
        try:
            order = await session.get(OrdersHistory, order_id)
            if not order:
                logging.warning(f"Заказ #{order_id} не найден при попытке изменить статус")
                return False
            order.status = ORDER_STATUS[str(status)]
            await session.commit()
            logging.info(f"Статус заказа #{order_id} изменён на '{ORDER_STATUS[str(status)]}'")
            return True
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при изменении статуса заказа #{order_id}: {e}")
            return False


async def update_order_after_payment(
    order_id: str,
    status: int,
    agent_transaction_id: str | None = None,
) -> bool:
    """
    Обновить статус заказа и сохранить agent_transaction_id после обработки платежа.

    Args:
        order_id: ID заказа в нашей БД.
        status: Числовой код статуса из ORDER_STATUS (1 — Оплачен, 3 — Отменён).
        agent_transaction_id: ID транзакции в системе Pay4Game (если есть).

    Returns:
        True при успехе, False при ошибке.
    """
    async with get_async_session() as session:
        try:
            order = await session.get(OrdersHistory, order_id)
            if not order:
                logging.warning(f"Заказ #{order_id} не найден при update_order_after_payment")
                return False
            order.status = ORDER_STATUS[str(status)]
            if agent_transaction_id is not None:
                order.agent_transaction_id = agent_transaction_id
            await session.commit()
            logging.info(
                f"Заказ #{order_id} обновлён: status='{ORDER_STATUS[str(status)]}', "
                f"agent_transaction_id={agent_transaction_id}"
            )
            return True
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при update_order_after_payment для заказа #{order_id}: {e}")
            return False


async def update_order_agent_transaction_id(order_id: str, agent_transaction_id: str) -> bool:
    """
    Сохранить agent_transaction_id в заказе сразу после создания платежа в Pay4Game.

    Args:
        order_id: ID заказа в нашей БД.
        agent_transaction_id: ID транзакции Pay4Game.

    Returns:
        True при успехе, False при ошибке.
    """
    async with get_async_session() as session:
        try:
            order = await session.get(OrdersHistory, order_id)
            if not order:
                logging.warning(f"Заказ #{order_id} не найден при update_order_agent_transaction_id")
                return False
            order.agent_transaction_id = agent_transaction_id
            await session.commit()
            logging.info(f"Заказ #{order_id}: сохранён agent_transaction_id={agent_transaction_id}")
            return True
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при update_order_agent_transaction_id для заказа #{order_id}: {e}")
            return False


async def update_steam_status(agent_transaction_id: str, steam_status: str) -> bool:
    """
    Обновить статус пополнения Steam по agent_transaction_id.

    Args:
        agent_transaction_id: ID транзакции Pay4Game.
        steam_status: Статус пополнения Steam (pending, success, error).

    Returns:
        True при успехе, False при ошибке.
    """
    async with get_async_session() as session:
        try:
            result = await session.execute(
                select(OrdersHistory)
                .where(OrdersHistory.agent_transaction_id == agent_transaction_id)
            )
            order = result.scalars().first()
            if not order:
                logging.warning(f"Заказ не найден при update_steam_status: agent_transaction_id={agent_transaction_id}")
                return False
            order.steam_status = steam_status
            await session.commit()
            logging.info(
                f"Заказ #{order.order_id}: steam_status обновлён на '{steam_status}' "
                f"(agent_transaction_id={agent_transaction_id})"
            )
            return True
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при update_steam_status для agent_transaction_id={agent_transaction_id}: {e}")
            return False


async def save_payment_message_id(order_id: str, message_id: int) -> bool:
    """
    Сохранить message_id сообщения с кнопками оплаты в заказе.

    Args:
        order_id: ID заказа в нашей БД.
        message_id: Telegram message_id сообщения с кнопками оплаты.

    Returns:
        True при успехе, False при ошибке.
    """
    async with get_async_session() as session:
        try:
            order = await session.get(OrdersHistory, order_id)
            if not order:
                logging.warning(f"Заказ #{order_id} не найден при save_payment_message_id")
                return False
            order.payment_message_id = message_id
            await session.commit()
            logging.info(f"Заказ #{order_id}: сохранён payment_message_id={message_id}")
            return True
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при save_payment_message_id для заказа #{order_id}: {e}")
            return False


async def get_payment_message_id(order_id: str) -> int | None:
    """
    Получить message_id сообщения с кнопками оплаты для удаления.

    Args:
        order_id: ID заказа в нашей БД.

    Returns:
        message_id или None, если заказ не найден или поле не задано.
    """
    async with get_async_session() as session:
        try:
            order = await session.get(OrdersHistory, order_id)
            if not order:
                logging.warning(f"Заказ #{order_id} не найден при get_payment_message_id")
                return None
            return order.payment_message_id
        except Exception as e:
            logging.error(f"Ошибка при get_payment_message_id для заказа #{order_id}: {e}")
            return None
