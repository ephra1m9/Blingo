from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


main_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="💵 Пополнить Steam", callback_data="steam_pay")]
    ]
)


def payment_keyboard(payment_url: str) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой оплаты для конкретного заказа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
            [InlineKeyboardButton(text="❌ Отменить платёж", callback_data="cancel_payment")],
        ]
    )
