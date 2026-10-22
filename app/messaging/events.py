from uuid import UUID

from pydantic import BaseModel

from app.domain.payment import PaymentCurrency


class PaymentCreatedEvent(BaseModel):
    payment_id: UUID
    amount: str
    currency: PaymentCurrency
