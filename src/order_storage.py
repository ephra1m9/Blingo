import time
import threading
from dataclasses import dataclass


@dataclass
class OrderData:
    steam_login: str
    user_id: int
    amount_rub: int
    created_at: float


class OrderStorage:
    """
    Потокобезопасное хранилище заказов в памяти.
    Ключ — числовой order_id (int), передаваемый в FreeKassa.
    Заказы автоматически удаляются через TTL секунд (по умолчанию 24 часа).
    """

    def __init__(self, ttl: int = 86400):
        self._store: dict[int, OrderData] = {}
        self._counter: int = int(time.time())
        self._lock = threading.Lock()
        self._ttl = ttl

    def create(self, steam_login: str, user_id: int, amount_rub: int) -> int:
        """Создаёт новый заказ и возвращает его числовой ID."""
        with self._lock:
            self._counter += 1
            order_id = self._counter
            self._store[order_id] = OrderData(
                steam_login=steam_login,
                user_id=user_id,
                amount_rub=amount_rub,
                created_at=time.time(),
            )
            return order_id

    def get(self, order_id: int) -> OrderData | None:
        """Возвращает данные заказа по ID или None если не найден / истёк TTL."""
        with self._lock:
            order = self._store.get(order_id)
            if order is None:
                return None
            if time.time() - order.created_at > self._ttl:
                del self._store[order_id]
                return None
            return order

    def delete(self, order_id: int) -> None:
        """Удаляет заказ из хранилища."""
        with self._lock:
            self._store.pop(order_id, None)


# Глобальный экземпляр хранилища
order_storage = OrderStorage()
