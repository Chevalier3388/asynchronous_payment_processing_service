import asyncio

from app.core.config import settings
from app.db.database import async_session_maker
from app.messaging.rabbitmq import RabbitMQ
from app.workers.outbox_publisher import OutboxPublisher


async def run() -> None:
    rabbitmq = RabbitMQ()
    await rabbitmq.connect()

    try:
        while True:
            async with async_session_maker() as session:
                publisher = OutboxPublisher(
                    session=session,
                    rabbitmq=rabbitmq,
                )

                await publisher.publish_once()
                await session.commit()

            await asyncio.sleep(settings.outbox_poll_interval)

    finally:
        await rabbitmq.close()


if __name__ == "__main__":
    asyncio.run(run())