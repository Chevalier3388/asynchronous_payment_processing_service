from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_async_session
from app.repositories.outbox_repository import OutboxRepository
from app.repositories.payment_repository import PaymentRepository
from app.schemas.payment import PaymentCreate, PaymentCreatedResponse
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


def get_payment_service(
    session: AsyncSession = Depends(get_async_session),
) -> PaymentService:
    payment_repository = PaymentRepository(session)
    outbox_repository = OutboxRepository(session)

    return PaymentService(
        payment_repository=payment_repository,
        outbox_repository=outbox_repository,
    )


@router.post(
    "",
    response_model=PaymentCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_payment(
    payment_data: PaymentCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentCreatedResponse:
    payment = await service.create_payment(
        payment_data,
        idempotency_key=idempotency_key,
    )

    return PaymentCreatedResponse.model_validate(payment)