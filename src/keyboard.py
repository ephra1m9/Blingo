from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


main_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="💵 Пополнить Steam", callback_data="steam_pay", style="primary")],
        [InlineKeyboardButton(text="📖 История пополнений", callback_data="my_orders_history")]
    ]
)


back_to_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_menu", style="danger")]
    ]
)


def promo_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для шага ввода промокода."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_promo")],
            [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_menu")],
        ]
    )


def payment_method_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора способа оплаты."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏦 СБП", callback_data="paymethod_sbp")],
            [InlineKeyboardButton(text="💳 Карта РФ", callback_data="paymethod_card")],
            [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_menu", style="danger")],
        ]
    )


def payment_keyboard(payment_url: str) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой оплаты для конкретного заказа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment_url, style="success")],
            [InlineKeyboardButton(text="❌ Отменить платёж", callback_data="cancel_payment", style="danger")],
        ]
    )
