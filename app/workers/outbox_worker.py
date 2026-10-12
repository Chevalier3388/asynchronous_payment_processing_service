import asyncio
import logging

from app.core.config import settings
from app.db.database import async_session_maker
from app.messaging.rabbitmq import RabbitMQ
from app.workers.outbox_publisher import OutboxPublisher


logger = logging.getLogger(__name__)


async def run() -> None:
    rabbitmq = RabbitMQ()

    try:
        await rabbitmq.connect()

        while True:
            try:
                async with async_session_maker() as session:
                    async with session.begin():
                        publisher = OutboxPublisher(
                            session=session,
                            rabbitmq=rabbitmq,
                        )
                        await publisher.publish_once()

            except Exception:
                logger.exception("Failed to publish Outbox events")

            await asyncio.sleep(settings.outbox_poll_interval)

    finally:
        await rabbitmq.close()


if __name__ == "__main__":
    asyncio.run(run())
