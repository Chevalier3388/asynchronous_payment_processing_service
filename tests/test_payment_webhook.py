from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.webhook import PaymentWebhookPayload


@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_webhook_contract_serializes_decimal_and_normalizes_utc(payment, status):
    payment.status = status
    payment.processed_at = datetime(2026, 10, 22, 15, 30, tzinfo=timezone(timedelta(hours=3)))

    payload = PaymentWebhookPayload.model_validate(payment).model_dump(mode="json")

    assert payload == {
        "payment_id": str(payment.id),
        "status": status,
        "amount": "100.00",
        "currency": "RUB",
        "processed_at": "2026-10-22T12:30:00Z",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "pending"),
        ("processed_at", None),
        ("processed_at", datetime(2026, 10, 22, 12, 30)),
    ],
)
def test_webhook_rejects_unfinished_payment_or_missing_timezone(payment, field, value):
    payment.status = "succeeded"
    payment.processed_at = datetime(2026, 10, 22, 12, 30, tzinfo=UTC)
    setattr(payment, field, value)

    with pytest.raises(ValidationError) as error:
        PaymentWebhookPayload.model_validate(payment)

    assert error.value.errors()[0]["loc"] == (field,)
