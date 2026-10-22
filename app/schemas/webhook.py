from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.db.models.payment import PaymentCurrency, PaymentStatus


class PaymentWebhookPayload(BaseModel):
    """Уведомление о сохранённом результате обработки платежа."""

    payment_id: UUID = Field(validation_alias="id")
    status: Literal[PaymentStatus.SUCCEEDED, PaymentStatus.FAILED]
    amount: Decimal
    currency: PaymentCurrency
    processed_at: AwareDatetime

    model_config = ConfigDict(from_attributes=True, validate_by_name=True)

    @field_validator("processed_at")
    @classmethod
    def normalize_processed_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)
