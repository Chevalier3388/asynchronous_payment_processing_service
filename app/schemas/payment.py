from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.domain.payment import PaymentCurrency, PaymentStatus


class PaymentCreate(BaseModel):
    amount: Decimal
    currency: PaymentCurrency
    description: str
    metadata: dict
    webhook_url: HttpUrl


class PaymentResponse(BaseModel):
    id: UUID
    amount: Decimal
    currency: PaymentCurrency
    description: str
    metadata: dict
    status: PaymentStatus
    idempotency_key: str
    webhook_url: HttpUrl
    created_at: datetime
    processed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class PaymentCreatedResponse(BaseModel):
    payment_id: UUID = Field(validation_alias="id")
    status: PaymentStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
