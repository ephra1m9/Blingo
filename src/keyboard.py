from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import CHANNEL_URL


channel_subscribe_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Подписаться на канал", url=CHANNEL_URL)],
    ]
)


main_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Пополнить Steam", callback_data="steam_pay", style="primary", icon_custom_emoji_id="5814587756810079398")],
        [InlineKeyboardButton(text="История пополнений", callback_data="my_orders_history", icon_custom_emoji_id="5778202206922608769")]
    ]
)


back_to_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Назад в меню", callback_data="back_to_menu", style="danger", icon_custom_emoji_id="5875082500023258804")]
    ]
)


def promo_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для шага ввода промокода."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data="skip_promo", icon_custom_emoji_id="5884050696679986441")],
            [InlineKeyboardButton(text="Назад в меню", callback_data="back_to_menu", style="danger", icon_custom_emoji_id="5875082500023258804")],
        ]
    )


def payment_method_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора способа оплаты."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="СБП", callback_data="paymethod_sbp", icon_custom_emoji_id="5217961106554769883"), InlineKeyboardButton(text="Карта РФ", callback_data="paymethod_card", icon_custom_emoji_id="5377377923076476823")],
            [InlineKeyboardButton(text="Назад в меню", callback_data="back_to_menu", style="danger", icon_custom_emoji_id="5875082500023258804")],
        ]
    )


def payment_keyboard(payment_url: str) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой оплаты для конкретного заказа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить", url=payment_url, style="success", icon_custom_emoji_id="6021331874528368703")],
            [InlineKeyboardButton(text="Отменить платёж", callback_data="cancel_payment", style="danger", icon_custom_emoji_id="5841541824803509441")],
        ]
    )
