import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from src.handlers import router
from src.db.db_connect import close_db
from src.webhook import create_webhook_app
from src.config import WEBHOOK_PORT
from src.throttling import ThrottlingMiddleware

import os

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)

BOT_TOKEN = os.getenv("BOT_TOKEN")


async def on_shutdown():
    await close_db()


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.message.middleware(ThrottlingMiddleware(max_calls=5, window_seconds=10.0))
    dp.callback_query.middleware(ThrottlingMiddleware(max_calls=5, window_seconds=10.0))

    dp.include_router(router)
    dp.shutdown.register(on_shutdown)

    webhook_app = create_webhook_app(bot)
    runner = web.AppRunner(webhook_app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=WEBHOOK_PORT)

    try:
        await site.start()
        logging.info(f"Webhook-сервер запущен на порту {WEBHOOK_PORT}")
        logging.info("Бот запускается...")

        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Ошибка при запуске: {e}")
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
