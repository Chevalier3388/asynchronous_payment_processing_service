import json

from aio_pika import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.messaging.rabbitmq import RabbitMQ
from app.repositories.outbox_repository import OutboxRepository


class OutboxPublisher:
    def __init__(
        self,
        session: AsyncSession,
        rabbitmq: RabbitMQ,
    ) -> None:
        self.repository = OutboxRepository(session)
        self.rabbitmq = rabbitmq

    async def publish_once(self) -> None:
        events = await self.repository.get_unpublished(
            settings.outbox_batch_size,
        )

        for event in events:
            message = Message(
                body=json.dumps(event.payload).encode(),
                content_type="application/json",
            )

            await self.rabbitmq.publish(
                message=message,
                routing_key=event.event_type,
            )

            await self.repository.mark_as_published(event.id)