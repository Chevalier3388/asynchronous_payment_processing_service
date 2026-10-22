from typing import Protocol
from uuid import UUID

from app.domain.payment import Payment, PaymentStatus


class PaymentGateway(Protocol):
    async def process(self, payment: Payment) -> PaymentStatus:
        """Возвращает результат обработки платежа шлюзом."""
        ...


class WebhookSender(Protocol):
    async def send(self, payment: Payment) -> None:
        """Отправляет результат; при ошибке доставки вызывает WebhookDeliveryError."""
        ...


class PaymentProcessingRepository(Protocol):
    async def get_by_id_for_update(self, payment_id: UUID) -> Payment | None: ...

    async def save(self, payment: Payment) -> Payment: ...
