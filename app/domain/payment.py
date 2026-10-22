from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4


class PaymentCurrency(StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class InvalidPaymentTransition(ValueError):
    """Попытка недопустимого изменения состояния платежа."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Payment:
    amount: Decimal
    currency: PaymentCurrency
    description: str
    metadata: dict
    idempotency_key: str
    webhook_url: str
    id: UUID = field(default_factory=uuid4)
    status: PaymentStatus = PaymentStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    processed_at: datetime | None = None
    webhook_delivered_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, PaymentStatus):
            raise ValueError("Payment status must be a PaymentStatus")
        if self.status == PaymentStatus.PENDING:
            if self.processed_at is not None:
                raise ValueError("Pending payment cannot have a processing date")
        elif self.processed_at is None or self.processed_at.utcoffset() is None:
            raise ValueError("Completed payment requires a timezone-aware processing date")
        if self.webhook_delivered_at is not None:
            if not self.is_completed:
                raise ValueError("Pending payment cannot have a delivered webhook")
            if self.webhook_delivered_at.utcoffset() is None:
                raise ValueError("Webhook delivery requires a timezone-aware date")

    @property
    def webhook_idempotency_key(self) -> str:
        return f"payment-result:{self.id}"

    def mark_webhook_delivered(self) -> Payment:
        if not self.is_completed:
            raise InvalidPaymentTransition("Cannot notify about a pending payment")
        if self.webhook_delivered_at is not None:
            return self
        return replace(self, webhook_delivered_at=datetime.now(UTC))

    @property
    def is_completed(self) -> bool:
        return self.status != PaymentStatus.PENDING

    def complete(self, status: PaymentStatus) -> Payment:
        """Возвращает завершённый платёж; повторное завершение запрещено."""
        if self.is_completed:
            raise InvalidPaymentTransition("Payment has already been completed")
        if not isinstance(status, PaymentStatus) or status == PaymentStatus.PENDING:
            raise InvalidPaymentTransition("Payment can only succeed or fail")
        return replace(self, status=status, processed_at=datetime.now(UTC))
