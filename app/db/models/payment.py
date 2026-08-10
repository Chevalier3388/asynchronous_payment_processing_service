from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PaymentCurrency(StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=False,
    )
    currency: Mapped[PaymentCurrency] = mapped_column(
        Enum(PaymentCurrency),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus),
        nullable=False,
        default=PaymentStatus.PENDING,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String,
        nullable=False,
        unique=True,
    )
    webhook_url: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )