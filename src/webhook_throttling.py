"""
aiohttp middleware для ограничения частоты запросов (Rate Limiting) на вебхук-эндпоинт.

Логика: sliding window — не более MAX_CALLS запросов за WINDOW_SECONDS секунд с одного IP.
При превышении лимита возвращается HTTP 429 Too Many Requests.
"""

import time
import logging
from collections import defaultdict, deque
from typing import Awaitable, Callable

from aiohttp import web


logger = logging.getLogger(__name__)

# Максимум запросов с одного IP за окно времени
MAX_CALLS: int = 10
# Размер окна в секундах
WINDOW_SECONDS: float = 60.0


class WebhookThrottlingMiddleware:
    """aiohttp middleware, ограничивающий частоту запросов по IP-адресу клиента. Применяется ко всем маршрутам приложения."""

    def __init__(
        self,
        max_calls: int = MAX_CALLS,
        window_seconds: float = WINDOW_SECONDS,
    ) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._calls: dict[str, deque] = defaultdict(deque)

    def _get_client_ip(self, request: web.Request) -> str:
        """Извлекает IP клиента с учётом заголовков реверс-прокси. Приоритет: X-Forwarded-For > X-Real-IP > peername."""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        peername = request.transport.get_extra_info("peername") if request.transport else None
        if peername:
            return peername[0]

        return "unknown"

    def _is_throttled(self, ip: str) -> bool:
        """Проверяет, превышен ли лимит для данного IP. Возвращает True если лимит превышен."""
        now = time.monotonic()
        window = self._calls[ip]

        while window and now - window[0] > self.window_seconds:
            window.popleft()

        if len(window) >= self.max_calls:
            return True

        window.append(now)
        return False

    @web.middleware
    async def middleware(
        self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.Response]],
    ) -> web.Response:
        ip = self._get_client_ip(request)

        if self._is_throttled(ip):
            logger.warning(
                f"WebhookThrottling: превышен лимит запросов с IP={ip}, "
                f"path={request.path}"
            )
            return web.Response(
                status=429,
                text="Too Many Requests",
                headers={"Retry-After": str(int(self.window_seconds))},
            )

        return await handler(request)
