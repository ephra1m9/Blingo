"""
Aiogram middleware для ограничения частоты запросов (Rate Limiting) от пользователей.

Логика: sliding window — не более MAX_CALLS вызовов за WINDOW_SECONDS секунд на user_id.
При превышении лимита сообщение игнорируется и пользователь получает предупреждение
(не чаще одного раза в NOTIFY_COOLDOWN секунд).
"""

import time
import logging
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject


logger = logging.getLogger(__name__)

# Максимум сообщений/нажатий за окно времени
MAX_CALLS: int = 5
# Размер окна в секундах
WINDOW_SECONDS: float = 10.0
# Минимальный интервал между предупреждениями одному пользователю (сек)
NOTIFY_COOLDOWN: float = 30.0


class ThrottlingMiddleware(BaseMiddleware):
    """
    Middleware для aiogram, ограничивающий частоту запросов по user_id.
    Применяется ко всем Message и CallbackQuery.
    """

    def __init__(
        self,
        max_calls: int = MAX_CALLS,
        window_seconds: float = WINDOW_SECONDS,
        notify_cooldown: float = NOTIFY_COOLDOWN,
    ) -> None:
        super().__init__()
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.notify_cooldown = notify_cooldown

        # user_id -> deque of timestamps
        self._calls: dict[int, deque] = defaultdict(deque)
        # user_id -> timestamp последнего предупреждения
        self._last_notify: dict[int, float] = {}

    def _is_throttled(self, user_id: int) -> bool:
        """
        Проверяет, превышен ли лимит для данного user_id.
        Добавляет текущий timestamp в окно и удаляет устаревшие.
        Возвращает True если лимит превышен.
        """
        now = time.monotonic()
        window = self._calls[user_id]

        # Удаляем вызовы вне окна
        while window and now - window[0] > self.window_seconds:
            window.popleft()

        if len(window) >= self.max_calls:
            return True

        window.append(now)
        return False

    def _should_notify(self, user_id: int) -> bool:
        """Возвращает True если пора снова уведомить пользователя о лимите."""
        now = time.monotonic()
        last = self._last_notify.get(user_id, 0.0)
        if now - last >= self.notify_cooldown:
            self._last_notify[user_id] = now
            return True
        return False

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Определяем user_id из события
        user_id: int | None = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id is not None and self._is_throttled(user_id):
            logger.warning(f"ThrottlingMiddleware: user_id={user_id} превысил лимит запросов")
            if self._should_notify(user_id):
                try:
                    if isinstance(event, Message):
                        await event.answer(
                            "⚠️ Слишком много запросов. Пожалуйста, подождите немного.",
                        )
                    elif isinstance(event, CallbackQuery):
                        await event.answer(
                            "⚠️ Слишком много запросов. Подождите немного.",
                            show_alert=True,
                        )
                except Exception as e:
                    logger.warning(f"Не удалось отправить throttle-уведомление user_id={user_id}: {e}")
            return  # Прерываем обработку

        return await handler(event, data)
