import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from src.handlers import router
from src.webhook import create_webhook_app
from src.config import WEBHOOK_PORT

import os

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)

BOT_TOKEN = os.getenv("BOT_TOKEN")


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # Создаём webhook-приложение и передаём ему экземпляр бота
    webhook_app = create_webhook_app(bot)
    runner = web.AppRunner(webhook_app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=WEBHOOK_PORT)

    try:
        await site.start()
        logging.info(f"Webhook-сервер запущен на порту {WEBHOOK_PORT}")
        logging.info("Бот запускается...")

        # Запускаем бота и webhook-сервер параллельно
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Ошибка при запуске: {e}")
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
