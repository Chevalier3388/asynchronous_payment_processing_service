from copy import deepcopy
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import Payment as PaymentModel
from app.domain.payment import Payment


def _to_domain(model: PaymentModel) -> Payment:
    return Payment(
        id=model.id,
        amount=model.amount,
        currency=model.currency,
        description=model.description,
        metadata=deepcopy(model.payment_metadata),
        status=model.status,
        idempotency_key=model.idempotency_key,
        webhook_url=model.webhook_url,
        created_at=model.created_at,
        processed_at=model.processed_at,
        webhook_delivered_at=model.webhook_delivered_at,
    )


def _to_record(payment: Payment) -> dict:
    return {
        "id": payment.id,
        "amount": payment.amount,
        "currency": payment.currency,
        "description": payment.description,
        "payment_metadata": deepcopy(payment.metadata),
        "status": payment.status,
        "idempotency_key": payment.idempotency_key,
        "webhook_url": payment.webhook_url,
        "created_at": payment.created_at,
        "processed_at": payment.processed_at,
        "webhook_delivered_at": payment.webhook_delivered_at,
    }


class PaymentRepository:
    """Хранит доменные платежи; ORM-модели остаются внутри репозитория."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, payment: Payment) -> Payment:
        model = PaymentModel(**_to_record(payment))
        self.session.add(model)
        await self.session.flush()
        return _to_domain(model)

    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        result = await self.session.execute(
            select(PaymentModel).where(PaymentModel.id == payment_id)
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model is not None else None

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        result = await self.session.execute(
            select(PaymentModel).where(PaymentModel.idempotency_key == idempotency_key)
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model is not None else None

    async def save(self, payment: Payment) -> Payment:
        """Сохраняет результат обработки платежа, ранее прочитанного с блокировкой."""
        model = await self.session.get(PaymentModel, payment.id)
        if model is None:
            raise LookupError(f"Payment {payment.id} not found")
        model.status = payment.status
        model.processed_at = payment.processed_at
        model.webhook_delivered_at = payment.webhook_delivered_at
        await self.session.flush()
        return _to_domain(model)

    async def create_if_absent(self, payment: Payment) -> Payment | None:
        statement = (
            insert(PaymentModel)
            .values(**_to_record(payment))
            .on_conflict_do_nothing(index_elements=[PaymentModel.idempotency_key])
            .returning(PaymentModel)
        )
        result = await self.session.execute(statement)
        model = result.scalar_one_or_none()
        return _to_domain(model) if model is not None else None

    async def get_by_id_for_update(self, payment_id: UUID) -> Payment | None:
        result = await self.session.execute(
            select(PaymentModel)
            .where(PaymentModel.id == payment_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model is not None else None
