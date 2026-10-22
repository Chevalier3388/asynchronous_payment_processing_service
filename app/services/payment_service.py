from uuid import UUID

from app.db.models.outbox import Outbox
from app.domain.payment import Payment
from app.repositories.outbox_repository import OutboxRepository
from app.repositories.payment_repository import PaymentRepository
from app.schemas.payment import PaymentCreate


class PaymentService:
    def __init__(
        self,
        payment_repository: PaymentRepository,
        outbox_repository: OutboxRepository,
    ) -> None:
        self.payment_repository = payment_repository
        self.outbox_repository = outbox_repository

    async def create_payment(
        self,
        payment_data: PaymentCreate,
        idempotency_key: str,
    ) -> Payment:
        existing_payment = await self.payment_repository.get_by_idempotency_key(
            idempotency_key,
        )

        if existing_payment is not None:
            return existing_payment

        payment = Payment(
            amount=payment_data.amount,
            currency=payment_data.currency,
            description=payment_data.description,
            metadata=payment_data.metadata,
            idempotency_key=idempotency_key,
            webhook_url=str(payment_data.webhook_url),
        )

        created_payment = await self.payment_repository.create_if_absent(payment)

        if created_payment is None:
            existing_payment = await self.payment_repository.get_by_idempotency_key(
                idempotency_key,
            )
            if existing_payment is None:
                raise RuntimeError("Payment not found after idempotency conflict")

            return existing_payment

        payment = created_payment

        outbox = Outbox(
            event_type="payments.new",
            payload={
                "payment_id": str(payment.id),
            },
        )

        await self.outbox_repository.create(outbox)

        return payment

    async def get_payment(self, payment_id: UUID) -> Payment | None:
        return await self.payment_repository.get_by_id(payment_id)
