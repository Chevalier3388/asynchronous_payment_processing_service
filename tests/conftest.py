import os
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

# Set test configuration before importing the application. No real services are used.
for name, value in {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "test_payments",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
    "RABBITMQ_HOST": "localhost",
    "RABBITMQ_PORT": "5672",
    "RABBITMQ_USER": "test",
    "RABBITMQ_PASSWORD": "test",
    "API_KEY": "test-api-key",
}.items():
    os.environ[name] = value

from app.api.payments import get_payment_service  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def payment():
    return SimpleNamespace(
        id=UUID("2292b6e9-ff88-44fe-8ac6-63889ed91bb2"),
        amount=Decimal("100.00"),
        currency="RUB",
        description="Тестовый платёж",
        payment_metadata={"order_id": "order-003"},
        status="pending",
        idempotency_key="test-payment-003",
        webhook_url="https://example.com/webhook",
        created_at=datetime(2026, 10, 12, 9, 33, 11, tzinfo=UTC),
        processed_at=None,
    )


@pytest.fixture
def payment_service(payment):
    return SimpleNamespace(
        create_payment=AsyncMock(return_value=payment),
        get_payment=AsyncMock(return_value=payment),
    )


@pytest.fixture
def client(payment_service):
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_payment_service] = lambda: payment_service
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


@pytest.fixture
def payment_payload():
    return {
        "amount": "100.00",
        "currency": "RUB",
        "description": "Тестовый платёж",
        "metadata": {"order_id": "order-003"},
        "webhook_url": "https://example.com/webhook",
    }


@pytest.fixture
def auth_headers():
    return {"X-API-Key": "test-api-key"}
