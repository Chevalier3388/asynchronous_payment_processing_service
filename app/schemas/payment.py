from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.db.models.payment import PaymentCurrency, PaymentStatus


class PaymentCreate(BaseModel):
    amount: Decimal
    currency: PaymentCurrency
    description: str
    metadata: dict
    idempotency_key: str
    webhook_url: HttpUrl


class PaymentResponse(BaseModel):
    id: UUID
    amount: Decimal
    currency: PaymentCurrency
    description: str
    metadata: dict = Field(validation_alias="payment_metadata")
    status: PaymentStatus
    idempotency_key: str
    webhook_url: HttpUrl
    created_at: datetime
    processed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)