from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import Payment, PaymentStatus


class PaymentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, payment: Payment) -> Payment:
        self.session.add(payment)
        await self.session.flush()

        return payment

    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        result = await self.session.execute(select(Payment).where(Payment.id == payment_id))

        return result.scalar_one_or_none()

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> Payment | None:
        result = await self.session.execute(
            select(Payment).where(
                Payment.idempotency_key == idempotency_key,
            )
        )

        return result.scalar_one_or_none()

    async def update_status(
        self,
        payment: Payment,
        status: PaymentStatus,
    ) -> Payment:
        payment.status = status
        payment.processed_at = datetime.now()

        await self.session.flush()

        return payment

    async def create_if_absent(self, payment: Payment) -> Payment | None:
        statement = (
            insert(Payment)
            .values(
                amount=payment.amount,
                currency=payment.currency,
                description=payment.description,
                payment_metadata=payment.payment_metadata,
                idempotency_key=payment.idempotency_key,
                webhook_url=payment.webhook_url,
            )
            .on_conflict_do_nothing(
                index_elements=[Payment.idempotency_key],
            )
            .returning(Payment)
        )

        result = await self.session.execute(statement)
        return result.scalar_one_or_none()
