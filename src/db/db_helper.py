import logging

from sqlalchemy import select

from .db_connect import get_async_session
from .models import UserInfo, OrdersHistory


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