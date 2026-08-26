import asyncio
import json
import random

from faststream.rabbit import RabbitMessage

from app.db.database import async_session_maker
from app.db.models.payment import PaymentStatus
from app.messaging.broker import broker, payments_queue
from app.repositories.payment_repository import PaymentRepository


@broker.subscriber(payments_queue)
async def process_payment(message: RabbitMessage) -> None:
    data = json.loads(message.body)
    payment_id = data["payment_id"]

    async with async_session_maker() as session:
        repository = PaymentRepository(session)
        payment = await repository.get_by_id(payment_id)

        if payment is None:
            print(f"Payment {payment_id} not found")
            return

        print(f"Processing payment: {payment.id}")

        await asyncio.sleep(random.uniform(2, 5))

        if random.random() < 0.9:
            status = PaymentStatus.SUCCEEDED
        else:
            status = PaymentStatus.FAILED

        await repository.update_status(payment, status)
        await session.commit()

        print(f"Payment {payment.id}: {status}")