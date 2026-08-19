from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_async_session
from app.repositories.outbox_repository import OutboxRepository
from app.repositories.payment_repository import PaymentRepository
from app.schemas.payment import PaymentCreate, PaymentResponse
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
    response_model=PaymentResponse,
)
async def create_payment(
    payment_data: PaymentCreate,
    service: PaymentService = Depends(get_payment_service),
) -> PaymentResponse:
    payment = await service.create_payment(payment_data)

    return PaymentResponse.model_validate(payment)