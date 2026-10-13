from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db import database
from app.main import app
from app.services.payment_service import PaymentService


@pytest.mark.parametrize("commit_fails", [False, True])
def test_create_response_requires_successful_commit(
    monkeypatch, payment, payment_payload, auth_headers, commit_fails
):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock(side_effect=RuntimeError("Commit failed") if commit_fails else None)
    session.rollback = AsyncMock()
    monkeypatch.setattr(database, "async_session_maker", lambda: session)
    monkeypatch.setattr(PaymentService, "create_payment", AsyncMock(return_value=payment))

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/payments",
            headers={**auth_headers, "Idempotency-Key": "transaction-check"},
            json=payment_payload,
        )

    assert response.status_code == (500 if commit_fails else 202)
    session.commit.assert_awaited_once()
    if commit_fails:
        session.rollback.assert_awaited_once()
    else:
        session.rollback.assert_not_awaited()
