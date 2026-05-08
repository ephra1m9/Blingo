import logging

from aiogram import Router, Bot, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, User
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import src.keyboard as kb

from .config import (
    STEAM_LOGIN_RE,
    MIN_AMOUNT,
    MAX_AMOUNT,
    COMMISSION,
    ORDER_STATUS,
)
from .db.db_helper import (
    get_or_create_user,
    change_order_status,
)
from .freekassa_payments import create_payment_url


router = Router()
logger = logging.getLogger(__name__)


# ========== FSM СОСТОЯНИЯ ==========
class SteamPayState(StatesGroup):
    waiting_login = State()
    waiting_amount = State()
    waiting_pay = State()


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def show_main_menu(target: Message, user: User, edit: bool = False):
    user_id = user.id
    user_name = user.full_name

    db_user, is_now = await get_or_create_user(user_id, user_name)

    text = (
        f"Привет <b>{user_name}</b>! 👋\n\n"
        f"Пополнение стим — {COMMISSION}%\n\n"
        f"<tg-emoji emoji-id='5463392464314315076'>👉</tg-emoji> Для пополнения баланса Steam нажми кнопку <b>«Пополнить Steam»</b> в меню ниже.\n\n"
        f"<a href='https://telegra.ph/Politika-konfidencialnosti-servisa-Blingo-Buy-05-06'>Политика конфиденциальности</a>\n"
        f"<a href='https://telegra.ph/Polzovatelskoe-soglashenie-servisa-Blingo-Buy-05-06'>Пользовательское соглашение</a>"
    )

    if edit:
        await target.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=kb.main_menu,
            disable_web_page_preview=True
        )
    else:
        await target.answer(
            text,
            parse_mode="HTML",
            reply_markup=kb.main_menu,
            disable_web_page_preview=True
        )


# ========== КОМАНДЫ ==========
@router.message(CommandStart())
async def cmd_start(m: Message):
    await show_main_menu(m, m.from_user, edit=False)


@router.message(Command("feedback"))
async def cmd_feedback(m: Message):
    await m.answer(
        "<b>Связь с нами</b>\n\n"
        "Email: nikitasrilanka@gmail.com\n"
        "Tg: @jedi_nick",
        parse_mode="HTML",
        disable_web_page_preview=True
    )


# ========== ОБРАБОТЧИКИ КНОПОК ==========
@router.callback_query(F.data == "steam_pay")
async def steam_pay(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SteamPayState.waiting_login)

    await callback.message.edit_text(
        "<b>Пополнение баланса Steam</b>\n\n"
        "Введите ваш логин Steam:\n\n"
        "<i><b>⚠️ Будьте внимательны!</b>\n"
        "Если вы введёте неправильный логин, средства зачислятся на аккаунт другого пользователя.</i>",
        parse_mode="HTML",
        reply_markup=kb.back_to_menu
    )
    
    await callback.answer()


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")

    if order_id:
        success = await change_order_status(order_id, 3)
        if success:
            logger.info(f"Заказ #{order_id} отменён пользователем {callback.from_user.id}")
        else:
            logger.warning(f"Не удалось отменить заказ #{order_id} для пользователя {callback.from_user.id}")
    else:
        logger.warning(f"cancel_payment: order_id не найден в state для пользователя {callback.from_user.id}")

    await state.clear()

    await callback.message.edit_text(
        "❌ <b>Платёж отменён.</b>\n\n"
        "Вы можете создать новый заказ в главном меню.",
        parse_mode="HTML",
        reply_markup=kb.back_to_menu,
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_main_menu(callback.message, callback.from_user, edit=True)
    await callback.answer()


# ========== FSM: ВВОД ЛОГИНА ==========
@router.message(SteamPayState.waiting_login)
async def process_login(m: Message, state: FSMContext):
    login = m.text.strip() if m.text else ""

    if not STEAM_LOGIN_RE.match(login):
        await m.answer(
            "❌ <b>Неверный логин Steam.</b>\n\n"
            "Логин может содержать только латинские буквы, цифры и символ подчёркивания (_), "
            "длина от 2 до 32 символов.\n\n"
            "Попробуйте ещё раз:",
            parse_mode="HTML",
            reply_markup=kb.back_to_menu
        )
        return

    await state.update_data(steam_login=login)
    await state.set_state(SteamPayState.waiting_amount)

    await m.answer(
        f"✅ Логин: <code>{login}</code>\n\n"
        f"Введите сумму пополнения в рублях:\n"
        f"<i>Минимум — {MIN_AMOUNT} руб., максимум — {MAX_AMOUNT:,} руб.</i>".replace(",", " "),
        parse_mode="HTML",
        reply_markup=kb.back_to_menu
    )


# ========== FSM: ВВОД СУММЫ ==========
@router.message(SteamPayState.waiting_amount)
async def process_amount(m: Message, state: FSMContext):
    raw = m.text.strip() if m.text else ""

    if not raw.lstrip('-').isdigit():
        await m.answer(
            "❌ Сумма должна быть целым числом.\n\n"
            "Попробуйте ещё раз:",
            parse_mode="HTML",
            reply_markup=kb.back_to_menu
        )
        return

    amount = int(raw)

    if amount < MIN_AMOUNT:
        await m.answer(
            f"❌ Минимальная сумма пополнения — <b>{MIN_AMOUNT} руб.</b>\n\n"
            f"Попробуйте ещё раз:",
            parse_mode="HTML",
            reply_markup=kb.back_to_menu
        )
        return

    if amount > MAX_AMOUNT:
        await m.answer(
            f"❌ Максимальная сумма пополнения — <b>{MAX_AMOUNT:,} руб.</b>\n\n".replace(",", " ") +
            "Попробуйте ещё раз:",
            parse_mode="HTML",
            reply_markup=kb.back_to_menu
        )
        return

    data = await state.get_data()
    login = data["steam_login"]
    total = round(amount * (1 + COMMISSION / 100))

    await state.set_state(SteamPayState.waiting_pay)

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

    await state.update_data(order_id=order_id)

    await m.answer(
        f"✅ <b>Заявка на пополнение:</b>\n\n"
        f"🎮 Логин Steam: <code>{login}</code>\n"
        f"💰 Сумма пополнения: <b>{amount} руб.</b>\n"
        f"💳 К оплате (с комиссией): <b>{total} руб.</b>\n\n"
        f"Нажми кнопку ниже для оплаты.\n"
        f"После успешной оплаты баланс Steam пополнится автоматически.",
        parse_mode="HTML",
        reply_markup=kb.payment_keyboard(payment_url),
    )
