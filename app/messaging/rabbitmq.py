import aio_pika
from aio_pika import Channel, Connection, Message
from pamqp.commands import Basic

from app.core.config import settings
from app.messaging.broker import payments_dlq, payments_queue


class RabbitMQ:
    def __init__(self) -> None:
        self.connection: Connection | None = None
        self.channel: Channel | None = None

    async def connect(self) -> None:
        self.connection = await aio_pika.connect_robust(
            settings.rabbitmq_url,
        )
        self.channel = await self.connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )
        await self.channel.declare_queue(
            payments_dlq.name,
            durable=True,
        )
        await self.channel.declare_queue(
            payments_queue.name,
            durable=True,
            arguments=payments_queue.arguments,
        )

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

        confirmation = await self.channel.default_exchange.publish(
            message,
            routing_key=routing_key,
            mandatory=True,
            timeout=10,
        )

        if not isinstance(confirmation, Basic.Ack):
            raise RuntimeError("RabbitMQ did not confirm publication")
