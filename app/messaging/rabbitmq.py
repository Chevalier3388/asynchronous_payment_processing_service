import aio_pika
from aio_pika import Channel, Connection, Message

from app.core.config import settings


class RabbitMQ:
    def __init__(self) -> None:
        self.connection: Connection | None = None
        self.channel: Channel | None = None

    async def connect(self) -> None:
        self.connection = await aio_pika.connect_robust(
            settings.rabbitmq_url,
        )
        self.channel = await self.connection.channel()

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()

    async def publish(
        self,
        message: Message,
        routing_key: str,
    ) -> None:
        if self.channel is None:
            raise RuntimeError("RabbitMQ is not connected")

        await self.channel.default_exchange.publish(
            message,
            routing_key=routing_key,
        )