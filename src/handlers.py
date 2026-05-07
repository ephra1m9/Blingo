import logging
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

from .config import (
    STEAM_LOGIN_RE,
    MIN_AMOUNT,
    MAX_AMOUNT,
    COMMISSION,
)
from .db.db_helper import (
    get_or_create_user
)
from .freekassa_payments import create_payment_url


router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(m: Message):
    user_id = m.from_user.id
    user_name = m.from_user.full_name

    user, is_now = await get_or_create_user(user_id, user_name)

    await m.answer(
        f"Привет <b>{user_name}</b>! 👋\n\n"
        f"Пополнение стим — 2%\n"
        f"При оплате по QR — 5%\n\n"
        f"<tg-emoji emoji-id='5463392464314315076'>👉</tg-emoji> Для пополнения баланса Steam используй команду /pay\n\n"
        f"<a href='https://telegra.ph/Politika-konfidencialnosti-servisa-Blingo-Buy-05-06'>Политика конфиденциальности</a>\n"
        f"<a href='https://telegra.ph/Polzovatelskoe-soglashenie-servisa-Blingo-Buy-05-06'>Пользовательское соглашение</a>",
        parse_mode="HTML",
        disable_web_page_preview=True
    )


@router.message(Command("pay"))
async def cmd_pay(m: Message, command: CommandObject):
    if not command.args:
        await m.answer(
            "❌ Укажи логин и сумму.\n\n"
            "Формат: <code>/pay [логин Steam] [сумма]</code>\n"
            "Пример: <code>/pay durov 1000</code>",
            parse_mode="HTML",
        )
        return

    parts = command.args.split()

    if len(parts) != 2:
        await m.answer(
            "❌ Неверный формат команды.\n\n"
            "Формат: <code>/pay [логин Steam] [сумма]</code>\n"
            "Пример: <code>/pay durov 1000</code>",
            parse_mode="HTML",
        )
        return

    login, amount_raw = parts

    if not STEAM_LOGIN_RE.match(login):
        await m.answer(
            "❌ Неверный логин Steam.\n\n"
            "Логин может содержать только латинские буквы, цифры и символ подчёркивания (_), "
            "длина от 2 до 32 символов.",
            parse_mode="HTML",
        )
        return

    if not amount_raw.lstrip('-').isdigit():
        await m.answer(
            "❌ Сумма должна быть целым числом.\n\n"
            "Пример: <code>/pay durov 1000</code>",
            parse_mode="HTML",
        )
        return

    amount = int(amount_raw)

    if amount < MIN_AMOUNT:
        await m.answer(
            f"❌ Минимальная сумма пополнения — <b>{MIN_AMOUNT} руб.</b>",
            parse_mode="HTML",
        )
        return

    if amount > MAX_AMOUNT:
        await m.answer(
            f"❌ Максимальная сумма пополнения — <b>{MAX_AMOUNT:,} руб.</b>".replace(",", " "),
            parse_mode="HTML",
        )
        return

    total = round(amount * (1 + COMMISSION))

    # Создаём ссылку на оплату через FreeKassa
    payment_url, order_id = await create_payment_url(
        amount_rub=amount,
        steam_login=login,
        user_id=m.from_user.id,
    )

    logger.info(
        f"Создан заказ FreeKassa: order_id={order_id}, "
        f"user_id={m.from_user.id}, steam={login}, amount={amount}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)]
        ]
    )

    await m.answer(
        f"✅ <b>Заявка на пополнение:</b>\n\n"
        f"🎮 Логин Steam: <code>{login}</code>\n"
        f"💰 Сумма пополнения: <b>{amount} руб.</b>\n"
        f"💳 К оплате (с комиссией): <b>{total} руб.</b>\n\n"
        f"Нажми кнопку ниже для оплаты.\n"
        f"После успешной оплаты баланс Steam пополнится автоматически.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )