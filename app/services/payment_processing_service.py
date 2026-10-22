from collections.abc import Awaitable, Callable
from uuid import UUID

from app.domain.payment import Payment
from app.services.errors import PaymentNotFoundError
from app.services.ports import PaymentGateway, PaymentProcessingRepository, WebhookSender


class PaymentProcessingService:
    def __init__(
        self,
        repository: PaymentProcessingRepository,
        gateway: PaymentGateway,
        webhook_sender: WebhookSender,
        commit: Callable[[], Awaitable[None]],
    ) -> None:
        self.repository = repository
        self.gateway = gateway
        self.webhook_sender = webhook_sender
        self.commit = commit

    async def process(self, payment_id: UUID) -> Payment:
        payment = await self.repository.get_by_id_for_update(payment_id)
        if payment is None:
            raise PaymentNotFoundError(f"Payment {payment_id} not found")

        if not payment.is_completed:
            status = await self.gateway.process(payment)
            payment = await self.repository.save(payment.complete(status))

        # Освобождаем блокировку и фиксируем результат до внешнего HTTP-запроса.
        await self.commit()

        # Повторно читаем состояние: другой consumer мог уже доставить уведомление.
        # Блокировка удерживается до фиксации доставки, сериализуя дубли сообщения.
        payment = await self.repository.get_by_id_for_update(payment_id)
        if payment is None:
            raise PaymentNotFoundError(f"Payment {payment_id} not found")
        if payment.webhook_delivered_at is not None:
            await self.commit()
            return payment

        await self._notify(payment)
        payment = await self.repository.save(payment.mark_webhook_delivered())
        await self.commit()
        return payment

    async def _notify(self, payment: Payment) -> None:
        await self.webhook_sender.send(payment)
