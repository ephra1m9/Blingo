import os
import sys
import asyncio
import logging

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


MYSQL_URL = os.getenv("MYSQL_URL")
_async_engine = None
_session_maker = None


def get_async_session() -> AsyncSession:
    global _async_engine, _session_maker

    if not _async_engine:
        if not MYSQL_URL:
            logging.error("MYSQL_URL не найден.")
            raise ValueError("MYSQL_URL is missing")
        
        try:
            _async_engine = create_async_engine(
                MYSQL_URL,
                echo=False,
                pool_pre_ping=True,
                pool_recycle=300
            )

            _session_maker = sessionmaker(
                _async_engine, class_=AsyncSession, expire_on_commit=False
            )

        except Exception as e:
            print(f"[DB] Ошибка создания подключения: {e}", file=sys.stderr)
            raise

    return _session_maker()


async def close_db():
    global _async_engine

    if _async_engine:
        try:
            logging.info("Закрываем соединения с БД...")
            await _async_engine.dispose()
            await asyncio.sleep(0.25)
        
        except Exception as e:
            logging.error(f"Ошибка при закрытии соедениния с БД: {e}")