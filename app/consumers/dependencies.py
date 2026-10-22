from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.db.database import async_session_maker
from app.integrations.payment_gateway import SimulatedPaymentGateway
from app.integrations.webhook_sender import HttpxWebhookSender
from app.repositories.payment_repository import PaymentRepository
from app.services.payment_processing_service import PaymentProcessingService


@asynccontextmanager
async def payment_processing_service() -> AsyncIterator[PaymentProcessingService]:
    async with async_session_maker() as session:
        async with httpx.AsyncClient(timeout=10.0) as client:
            yield PaymentProcessingService(
                repository=PaymentRepository(session),
                gateway=SimulatedPaymentGateway(),
                webhook_sender=HttpxWebhookSender(client),
                commit=session.commit,
            )
