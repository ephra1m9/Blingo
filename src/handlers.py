import asyncio
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
    CHANNEL_ID,
)
from .bot_helper import (
    get_welcome_phrase
)
from .db.db_helper import (
    get_or_create_user,
    get_user_orders,
    change_order_status,
    get_order,
    save_payment_message_id,
    get_payment_message_id,
)
from .pay4game_payments import create_payment_url, validate_promo
from .pay4game_poller import wait_for_payment_and_notify


router = Router()
logger = logging.getLogger(__name__)

# Метки статусов пополнения Steam
STEAM_STATUS_LABELS = {
    "pending": "⏳ В обработке",
    "success": "✅ Выполнено",
    "error":   "❌ Ошибка",
}


# ========== FSM СОСТОЯНИЯ ==========
class SteamPayState(StatesGroup):
    waiting_login = State()
    waiting_amount = State()
    waiting_promo = State()
    waiting_method = State()
    waiting_pay = State()


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def safe_delete_message(bot: Bot, chat_id: int, message_id: int) -> None:
    """
    Безопасно удаляет сообщение, игнорируя ошибки
    (например, если сообщение уже удалено).
    """
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.debug(f"Не удалось удалить сообщение {message_id} в чате {chat_id}: {e}")


async def is_user_subscribed(bot: Bot, user_id: int) -> bool:
    """Проверяет, подписан ли пользователь на канал."""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning(f"Ошибка проверки подписки user_id={user_id}: {e}")
        return False


async def show_main_menu(target: Message, user: User, edit: bool = False):
    user_id = user.id
    user_name = user.full_name

    db_user, is_now = await get_or_create_user(user_id, user_name)

    welcome_text = get_welcome_phrase(user_name)

    text = (
        welcome_text +
        f"\n\n" +
        f"<tg-emoji emoji-id='5188481279963715781'>🚀</tg-emoji> Пополнение Steam с минимальной комиссией — всего {COMMISSION}%!\n\n"
        f"<tg-emoji emoji-id='5319302290127991242'>💎</tg-emoji> Получи промокод на скидку в нашем канале <a href='https://t.me/BlingoCom'>BlingoCom</a>\n\n"
        f"<tg-emoji emoji-id='5460755126761312667'>🚩</tg-emoji> <b>Доступные регионы для пополнения:</b>\n"
        f"России, Азербайджан, Армения, Беларусь, Казахстан, Кыргызстан, Молдова, Таджикистан, Туркменистан, Узбекистан, Украина\n\n"
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
        "Tg: @MiamiBuyer",
        parse_mode="HTML",
        disable_web_page_preview=True
    )


# ========== ОБРАБОТЧИКИ КНОПОК ==========
@router.callback_query(F.data == "steam_pay")
async def steam_pay(callback: CallbackQuery, state: FSMContext):
    # Проверка подписки на канал
    if not await is_user_subscribed(callback.bot, callback.from_user.id):
        await callback.answer(
            "⚠️ Чтобы пополнить Steam, подпишитесь на наш канал.",
            show_alert=True,
        )
        await callback.message.answer(
            "🔔 <b>Подпишитесь на канал, чтобы продолжить:</b>",
            parse_mode="HTML",
            reply_markup=kb.channel_subscribe_kb,
        )
        return

    await state.set_state(SteamPayState.waiting_login)

    # Удаляем главное меню
    await safe_delete_message(callback.bot, callback.message.chat.id, callback.message.message_id)

    # Отправляем новое сообщение с запросом логина
    msg = await callback.message.answer(
        "<b>Пополнение баланса Steam</b>\n\n"
        "Введите ваш логин Steam:\n\n"
        "<i><b>⚠️ Будьте внимательны!</b>\n"
        "Если вы введёте неправильный логин, средства зачислятся на аккаунт другого пользователя.</i>",
        parse_mode="HTML",
        reply_markup=kb.back_to_menu
    )

    await state.update_data(bot_message_id=msg.message_id)
    await callback.answer()


@router.callback_query(F.data == "my_orders_history")
async def my_orders_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    orders_list = await get_user_orders(user_id)

    if orders_list:
        lines = []
        for order in orders_list:
            date_str = order.created_at.strftime("%d.%m.%Y %H:%M")
            agent_id = order.agent_transaction_id if order.agent_transaction_id else "—"
            steam_status_label = STEAM_STATUS_LABELS.get(
                order.steam_status or "", "—"
            )

            lines.append(
                f"<b>Заказ №{order.order_id}:</b>\n"
                f"<b>Дата:</b> {date_str}\n"
                f"<b>ID транзакции:</b> <code>{agent_id}</code>\n"
                f"<b>Логин Steam:</b> {order.steam_login}\n"
                f"<b>Сумма:</b> {order.amount} руб.\n"
                f"<b>Статус оплаты:</b> {order.status}\n"
                f"<b>Статус пополнения:</b> {steam_status_label}"
            )

        text = "<b>📖 История пополнений</b>\n\n" + "\n\n".join(lines)

        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=kb.back_to_menu
        )
        await callback.answer()

    else:
        await callback.answer("История не найдена", show_alert=True)


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery, state: FSMContext):
    from .pay4game_poller import cancel_polling

    data = await state.get_data()
    order_id = data.get("order_id")

    if order_id:
        order_info = await get_order(order_id)

        if order_info.status == "Создан":
            success = await change_order_status(order_id, 3)
            if success:
                logger.info(f"Заказ #{order_id} отменён пользователем {callback.from_user.id}")
                # Останавливаем фоновую задачу поллинга
                cancel_polling(order_id)
            else:
                logger.warning(f"Не удалось отменить заказ #{order_id} для пользователя {callback.from_user.id}")
                await callback.answer("Отмена невозможна: заказ уже оплачен или обрабатывается.", show_alert=True)
                await state.clear()
                return
        else:
            logger.warning(f"Не удалось отменить заказ #{order_id} для пользователя {callback.from_user.id}")
            await callback.answer("Отмена невозможна: заказ уже оплачен или обрабатывается.", show_alert=True)
            await state.clear()
            return
    else:
        logger.warning(f"cancel_payment: order_id не найден в state для пользователя {callback.from_user.id}")

    await state.clear()

    # Удаляем сообщение с кнопками оплаты
    payment_msg_id = await get_payment_message_id(order_id) if order_id else None
    if payment_msg_id:
        await safe_delete_message(callback.bot, callback.message.chat.id, payment_msg_id)

    await callback.message.answer(
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
        # Удаляем сообщение пользователя с неверным логином
        await safe_delete_message(m.bot, m.chat.id, m.message_id)
        await m.answer(
            "❌ <b>Неверный логин Steam.</b>\n\n"
            "Логин может содержать только латинские буквы, цифры и символ подчёркивания (_), "
            "длина от 2 до 32 символов.\n\n"
            "Попробуйте ещё раз:",
            parse_mode="HTML",
            reply_markup=kb.back_to_menu
        )
        return

    # Удаляем сообщение пользователя с логином
    await safe_delete_message(m.bot, m.chat.id, m.message_id)

    # Удаляем предыдущее сообщение бота (запрос логина)
    data = await state.get_data()
    prev_bot_msg_id = data.get("bot_message_id")
    if prev_bot_msg_id:
        await safe_delete_message(m.bot, m.chat.id, prev_bot_msg_id)

    # Логин принят — сразу запрашиваем сумму
    msg = await m.answer(
        f"✅ Логин: <code>{login}</code>\n\n"
        f"Введите сумму пополнения в рублях:\n"
        f"<i>Минимум — {MIN_AMOUNT} руб., максимум — {MAX_AMOUNT:,} руб.</i>".replace(",", " "),
        parse_mode="HTML",
        reply_markup=kb.back_to_menu
    )
    await state.update_data(steam_login=login, bot_message_id=msg.message_id)
    await state.set_state(SteamPayState.waiting_amount)


# ========== FSM: ВВОД СУММЫ ==========
@router.message(SteamPayState.waiting_amount)
async def process_amount(m: Message, state: FSMContext):
    raw = m.text.strip() if m.text else ""

    if not raw.lstrip('-').isdigit():
        await safe_delete_message(m.bot, m.chat.id, m.message_id)
        await m.answer(
            "❌ Сумма должна быть целым числом.\n\n"
            "Попробуйте ещё раз:",
            parse_mode="HTML",
            reply_markup=kb.back_to_menu
        )
        return

    amount = int(raw)

    if amount < MIN_AMOUNT:
        await safe_delete_message(m.bot, m.chat.id, m.message_id)
        await m.answer(
            f"❌ Минимальная сумма пополнения — <b>{MIN_AMOUNT} руб.</b>\n\n"
            f"Попробуйте ещё раз:",
            parse_mode="HTML",
            reply_markup=kb.back_to_menu
        )
        return

    if amount > MAX_AMOUNT:
        await safe_delete_message(m.bot, m.chat.id, m.message_id)
        await m.answer(
            f"❌ Максимальная сумма пополнения — <b>{MAX_AMOUNT:,} руб.</b>\n\n".replace(",", " ") +
            "Попробуйте ещё раз:",
            parse_mode="HTML",
            reply_markup=kb.back_to_menu
        )
        return

    # Удаляем сообщение пользователя с суммой
    await safe_delete_message(m.bot, m.chat.id, m.message_id)

    # Удаляем предыдущее сообщение бота (подтверждение логина / ввод суммы)
    data = await state.get_data()
    prev_bot_msg_id = data.get("bot_message_id")
    if prev_bot_msg_id:
        await safe_delete_message(m.bot, m.chat.id, prev_bot_msg_id)

    await state.update_data(amount=amount)
    await state.set_state(SteamPayState.waiting_promo)

    msg = await m.answer(
        "🎟️ <b>Есть промокод?</b>\n\n"
        "Введите промокод или нажмите <b>«Пропустить»</b>, если его нет.",
        parse_mode="HTML",
        reply_markup=kb.promo_keyboard(),
    )

    await state.update_data(bot_message_id=msg.message_id)


# ========== ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: СОЗДАНИЕ ПЛАТЕЖА ==========
async def _proceed_to_payment(
    message: Message,
    state: FSMContext,
    user_id: int,
    method: str,
) -> None:
    """Создаёт платёж Pay4Game и запускает поллинг. Используется из обработчика выбора метода оплаты."""
    data = await state.get_data()
    login = data["steam_login"]
    amount = data["amount"]
    promo = data.get("promo")
    promo_commission = data.get("promo_commission", COMMISSION)
    total = round(amount * (1 + promo_commission / 100), 2)

    # Удаляем предыдущее сообщение бота (выбор метода оплаты)
    prev_bot_msg_id = data.get("bot_message_id")
    if prev_bot_msg_id:
        await safe_delete_message(message.bot, message.chat.id, prev_bot_msg_id)

    await state.set_state(SteamPayState.waiting_pay)

    try:
        payment_url, order_id, agent_transaction_id = await create_payment_url(
            amount_rub=amount,
            steam_login=login,
            user_id=user_id,
            method=method,
            commission=promo_commission,
            promo=promo,
        )
    except Exception as e:
        logger.error(f"Ошибка создания платежа Pay4Game: {e}")
        await state.clear()
        await message.answer(
            "❌ <b>Не удалось создать платёж.</b>\n\n"
            "Попробуйте позже или обратитесь в поддержку.",
            parse_mode="HTML",
            reply_markup=kb.back_to_menu,
        )
        return

    logger.info(
        f"Создан заказ Pay4Game: order_id={order_id}, "
        f"user_id={user_id}, steam={login}, amount={amount}, "
        f"commission={promo_commission}%, promo={promo!r}, "
        f"agent_transaction_id={agent_transaction_id}"
    )

    await state.update_data(order_id=order_id)

    # Формируем текст с учётом промокода
    promo_line = ""
    if promo and promo_commission != COMMISSION:
        if promo_commission == 0:
            promo_line = "🎟️ Промокод применён! Комиссия 0%.\n"
        else:
            promo_line = f"🎟️ Промокод применён! Комиссия {promo_commission}%.\n"

    payment_msg = await message.answer(
        f"✅ <b>Заявка на пополнение:</b>\n\n"
        f"🎮 Логин Steam: <code>{login}</code>\n"
        f"💰 Сумма пополнения: <b>{amount} руб.</b>\n"
        f"💳 К оплате: <b>{total:.2f} руб.</b>\n"
        f"{promo_line}\n"
        f"Нажми кнопку ниже для оплаты.\n"
        f"После успешной оплаты баланс Steam пополнится автоматически.",
        parse_mode="HTML",
        reply_markup=kb.payment_keyboard(payment_url),
    )

    # Сохраняем message_id сообщения с кнопками оплаты в БД для последующего удаления
    await save_payment_message_id(order_id, payment_msg.message_id)

    # Запускаем фоновый поллинг статуса платежа
    if agent_transaction_id:
        asyncio.create_task(
            wait_for_payment_and_notify(
                bot=message.bot,
                user_id=user_id,
                agent_transaction_id=agent_transaction_id,
                order_id=order_id,
            )
        )
    else:
        logger.warning(f"Поллинг не запущен: agent_transaction_id отсутствует для order_id={order_id}")


# ========== FSM: ВВОД ПРОМОКОДА ==========
@router.message(SteamPayState.waiting_promo)
async def process_promo(m: Message, state: FSMContext):
    promo = m.text.strip() if m.text else ""

    # Удаляем сообщение пользователя с промокодом
    await safe_delete_message(m.bot, m.chat.id, m.message_id)

    # Удаляем предыдущее сообщение бота (запрос промокода)
    data = await state.get_data()
    prev_bot_msg_id = data.get("bot_message_id")
    if prev_bot_msg_id:
        await safe_delete_message(m.bot, m.chat.id, prev_bot_msg_id)

    # Показываем сообщение о проверке
    checking_msg = await m.answer(
        "⏳ <b>Проверяем промокод...</b>",
        parse_mode="HTML",
    )

    result = await validate_promo(promo)

    # Удаляем сообщение о проверке
    await safe_delete_message(m.bot, m.chat.id, checking_msg.message_id)

    if result.get("success"):
        # Промокод применён
        promo_commission = result["commission"]
        await state.update_data(promo=promo, promo_commission=promo_commission)

        if promo_commission == 0:
            success_text = "🎟️ <b>Промокод применён!</b> Комиссия 0% — оплата без комиссии."
        else:
            success_text = f"🎟️ <b>Промокод применён!</b> Комиссия снижена до {promo_commission}%."

        await state.set_state(SteamPayState.waiting_method)
        msg = await m.answer(
            f"{success_text}\n\n<b>💳 Выберите способ оплаты:</b>",
            parse_mode="HTML",
            reply_markup=kb.payment_method_keyboard(),
        )
        await state.update_data(bot_message_id=msg.message_id)

    elif result.get("error") == "Сервис проверки промокодов недоступен":
        # Сервис недоступен — пропускаем со стандартной комиссией
        logger.warning("Сервис проверки промокодов недоступен, пропускаем")
        await state.update_data(promo=promo)
        await state.set_state(SteamPayState.waiting_method)
        msg = await m.answer(
            "⚠️ <b>Не удалось проверить промокод</b> (сервис временно недоступен).\n"
            "Продолжаем со стандартной комиссией.\n\n"
            "<b>💳 Выберите способ оплаты:</b>",
            parse_mode="HTML",
            reply_markup=kb.payment_method_keyboard(),
        )
        await state.update_data(bot_message_id=msg.message_id)

    else:
        # Промокод не принят — даём ввести заново или пропустить
        error_text = result.get("error", "Неизвестная ошибка")
        await state.set_state(SteamPayState.waiting_promo)
        msg = await m.answer(
            f"❌ <b>{error_text}</b>\n\n"
            "Введите другой промокод или нажмите <b>«Пропустить»</b>:",
            parse_mode="HTML",
            reply_markup=kb.promo_keyboard(),
        )
        await state.update_data(bot_message_id=msg.message_id)


@router.callback_query(F.data == "skip_promo")
async def skip_promo(callback: CallbackQuery, state: FSMContext):
    await state.update_data(promo=None)

    await safe_delete_message(callback.bot, callback.message.chat.id, callback.message.message_id)

    data = await state.get_data()
    prev_bot_msg_id = data.get("bot_message_id")
    if prev_bot_msg_id:
        await safe_delete_message(callback.bot, callback.message.chat.id, prev_bot_msg_id)

    await callback.answer()
    await state.set_state(SteamPayState.waiting_method)

    msg = await callback.message.answer(
        "<b>💳 Выберите способ оплаты:</b>",
        parse_mode="HTML",
        reply_markup=kb.payment_method_keyboard(),
    )

    await state.update_data(bot_message_id=msg.message_id)


# ========== FSM: ВЫБОР СПОСОБА ОПЛАТЫ ==========
@router.callback_query(F.data.startswith("paymethod_"), SteamPayState.waiting_method)
async def process_payment_method(callback: CallbackQuery, state: FSMContext):
    """Сохраняет выбранный метод оплаты и запускает создание платежа."""
    method = callback.data.removeprefix("paymethod_")
    await state.update_data(method=method)
    await callback.answer()
    await _proceed_to_payment(callback.message, state, callback.from_user.id, method)
