from app.db.models.outbox import Outbox
from app.db.models.payment import Payment
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
    ) -> Payment:
        existing_payment = await self.payment_repository.get_by_idempotency_key(
            payment_data.idempotency_key,
        )

        if existing_payment is not None:
            return existing_payment

        payment = Payment(
            amount=payment_data.amount,
            currency=payment_data.currency,
            description=payment_data.description,
            payment_metadata=payment_data.metadata,
            idempotency_key=payment_data.idempotency_key,
            webhook_url=str(payment_data.webhook_url),
        )

        await self.payment_repository.create(payment)

        outbox = Outbox(
            event_type="payments.new",
            payload={
                "payment_id": str(payment.id),
            },
        )

        await self.outbox_repository.create(outbox)

        return payment