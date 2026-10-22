import json
from uuid import UUID

from faststream.exceptions import RejectMessage
from faststream.rabbit import RabbitMessage

from app.consumers.dependencies import payment_processing_service
from app.messaging.broker import broker, payments_queue
from app.services.errors import PaymentNotFoundError, WebhookDeliveryExhaustedError


@broker.subscriber(payments_queue)
async def process_payment(message: RabbitMessage) -> None:
    data = json.loads(message.body)
    payment_id = UUID(data["payment_id"])

    try:
        async with payment_processing_service() as service:
            payment = await service.process(payment_id)
    except PaymentNotFoundError as error:
        print(error)
        return
    except WebhookDeliveryExhaustedError:
        raise RejectMessage(requeue=False) from None

    print(f"Payment {payment.id}: {payment.status}")
