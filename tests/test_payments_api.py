from decimal import Decimal
from uuid import UUID

import pytest

pytestmark = pytest.mark.anyio

PAYMENTS_URL = "/api/v1/payments"


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("api_key", [None, "wrong-key"])
async def test_rejects_missing_or_invalid_api_key(
    client, payment, payment_service, payment_payload, method, api_key
):
    headers = {"Idempotency-Key": "test-payment-003"}
    if api_key is not None:
        headers["X-API-Key"] = api_key
    url = PAYMENTS_URL if method == "POST" else f"{PAYMENTS_URL}/{payment.id}"

    response = await client.request(method, url, headers=headers, json=payment_payload)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}
    payment_service.create_payment.assert_not_awaited()
    payment_service.get_payment.assert_not_awaited()


async def test_create_payment_returns_accepted_contract(
    client, auth_headers, payment_payload, payment, payment_service
):
    response = await client.post(
        PAYMENTS_URL,
        headers={**auth_headers, "Idempotency-Key": "test-payment-003"},
        json=payment_payload,
    )

    assert response.status_code == 202
    assert response.json() == {
        "payment_id": str(payment.id),
        "status": "pending",
        "created_at": "2026-10-12T09:33:11Z",
    }
    payment_service.create_payment.assert_awaited_once()
    args, kwargs = payment_service.create_payment.await_args
    assert kwargs == {"idempotency_key": "test-payment-003"}
    assert args[0].amount == Decimal("100.00")
    assert args[0].metadata == payment_payload["metadata"]
    assert "idempotency_key" not in args[0].model_dump()


async def test_create_requires_idempotency_header(
    client, auth_headers, payment_payload, payment_service
):
    response = await client.post(PAYMENTS_URL, headers=auth_headers, json=payment_payload)

    assert response.status_code == 422
    assert any(error["loc"] == ["header", "Idempotency-Key"] for error in response.json()["detail"])
    payment_service.create_payment.assert_not_awaited()


@pytest.mark.parametrize(
    ("field", "value"),
    [("currency", "GBP"), ("amount", "not-a-number"), ("webhook_url", "not-a-url")],
)
async def test_create_rejects_invalid_body(
    client, auth_headers, payment_payload, payment_service, field, value
):
    payment_payload[field] = value
    response = await client.post(
        PAYMENTS_URL,
        headers={**auth_headers, "Idempotency-Key": "test-payment-003"},
        json=payment_payload,
    )

    assert response.status_code == 422
    assert any(error["loc"] == ["body", field] for error in response.json()["detail"])
    payment_service.create_payment.assert_not_awaited()


@pytest.mark.parametrize("payment_status", ["pending", "succeeded", "failed"])
async def test_get_payment_returns_details(
    client, auth_headers, payment, payment_service, payment_status
):
    payment.status = payment_status
    if payment_status != "pending":
        payment.processed_at = payment.created_at

    response = await client.get(f"{PAYMENTS_URL}/{payment.id}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {
        "id": str(payment.id),
        "amount": "100.00",
        "currency": "RUB",
        "description": "Тестовый платёж",
        "metadata": {"order_id": "order-003"},
        "status": payment_status,
        "idempotency_key": "test-payment-003",
        "webhook_url": "https://example.com/webhook",
        "created_at": "2026-10-12T09:33:11Z",
        "processed_at": None if payment_status == "pending" else "2026-10-12T09:33:11Z",
    }
    payment_service.get_payment.assert_awaited_once_with(payment.id)


async def test_get_unknown_payment_returns_404(client, auth_headers, payment_service):
    payment_service.get_payment.return_value = None
    missing_id = UUID("00000000-0000-0000-0000-000000000000")

    response = await client.get(f"{PAYMENTS_URL}/{missing_id}", headers=auth_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Payment not found"}
    payment_service.get_payment.assert_awaited_once_with(missing_id)


async def test_get_invalid_uuid_returns_422(client, auth_headers, payment_service):
    response = await client.get(f"{PAYMENTS_URL}/abc", headers=auth_headers)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "payment_id"]
    payment_service.get_payment.assert_not_awaited()
