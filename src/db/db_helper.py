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


async def create_order(user_id: int, steam_login: str, amount: int) -> int | None:
    """Создать новый заказ, вернуть order_id из БД"""
    async with get_async_session() as session:
        try:
            order = OrdersHistory(
                user_id=user_id,
                steam_login=steam_login,
                amount=amount
            )

            session.add(order)
            await session.commit()
            await session.refresh(order)
            logging.info(f"Добавлен новый заказ #{order.order_id} на сумму {amount} руб.")
            return order.order_id

        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при создании заказа: {e}")
            return None


async def get_order(order_id: int) -> OrdersHistory | None:
    """Получить заказ из БД по order_id"""
    async with get_async_session() as session:
        try:
            order = await session.get(OrdersHistory, order_id)
            return order
        except Exception as e:
            logging.error(f"Ошибка при получении заказа #{order_id}: {e}")
            return None


async def change_order_status(order_id: int, status: int) -> bool:
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
    order_id: int,
    status: int,
    dessly_order_id: str | None = None,
) -> bool:
    """
    Обновить статус заказа и сохранить dessly_order_id после обработки платежа.

    Args:
        order_id: ID заказа в нашей БД.
        status: Числовой код статуса из ORDER_STATUS (1 — Оплачен, 3 — Отменён).
        dessly_order_id: ID заказа в системе Dessly (если есть).

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
            if dessly_order_id is not None:
                order.dessly_order_id = dessly_order_id
            await session.commit()
            logging.info(
                f"Заказ #{order_id} обновлён: status='{ORDER_STATUS[str(status)]}', "
                f"dessly_order_id={dessly_order_id}"
            )
            return True
        except Exception as e:
            await session.rollback()
            logging.error(f"Ошибка при update_order_after_payment для заказа #{order_id}: {e}")
            return False
