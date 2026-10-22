import json
from uuid import UUID

from faststream.exceptions import RejectMessage
from faststream.rabbit import RabbitMessage
from pamqp.commands import Basic
from sqlalchemy.exc import SQLAlchemyError

from app.consumers.dependencies import payment_processing_service
from app.messaging.broker import (
    broker,
    payments_queue,
    payments_retry_1s,
    payments_retry_2s,
)
from app.services.errors import (
    PaymentGatewayError,
    PaymentNotFoundError,
    PermanentWebhookDeliveryError,
    WebhookDeliveryError,
)

MAX_RETRIES = 2
RETRY_HEADER = "x-payment-retry-count"


@broker.subscriber(payments_queue)
async def process_payment(message: RabbitMessage) -> None:
    try:
        data = json.loads(message.body)
        payment_id = UUID(data["payment_id"])
        retry_count = int((message.headers or {}).get(RETRY_HEADER, 0))
        if retry_count < 0 or retry_count > MAX_RETRIES:
            raise ValueError("Invalid payment retry count")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"Rejecting malformed payment message: {error}")
        raise RejectMessage(requeue=False) from error

    try:
        async with payment_processing_service() as service:
            payment = await service.process(payment_id)
    except (PaymentNotFoundError, PermanentWebhookDeliveryError) as error:
        print(f"Rejecting payment {payment_id}: {error}")
        raise RejectMessage(requeue=False) from error
    except (
        PaymentGatewayError,
        SQLAlchemyError,
        WebhookDeliveryError,
        TimeoutError,
        ConnectionError,
        OSError,
    ) as error:
        if retry_count >= MAX_RETRIES:
            print(f"Retry limit reached for payment {payment_id}: {error}")
            raise RejectMessage(requeue=False) from error

        retry_queue = payments_retry_1s if retry_count == 0 else payments_retry_2s
        confirmation = await broker.publish(
            message.body,
            queue=retry_queue,
            headers={RETRY_HEADER: retry_count + 1},
            content_type="application/json",
            persist=True,
        )
        if not isinstance(confirmation, Basic.Ack):
            raise RuntimeError("RabbitMQ did not confirm the retry message") from error
        print(f"Scheduled retry {retry_count + 1} for payment {payment_id}: {error}")
        return
    except Exception as error:
        print(f"Rejecting unexpected processing error for payment {payment_id}: {error}")
        raise RejectMessage(requeue=False) from error

    print(f"Payment {payment.id}: {payment.status}")
