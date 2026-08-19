import aio_pika
from aio_pika import Channel, Connection

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