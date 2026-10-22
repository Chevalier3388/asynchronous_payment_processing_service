import json
import logging
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
logger = logging.getLogger(__name__)


@broker.subscriber(payments_queue)
async def process_payment(message: RabbitMessage) -> None:
    try:
        data = json.loads(message.body)
        payment_id = UUID(data["payment_id"])
        retry_count = int((message.headers or {}).get(RETRY_HEADER, 0))
        if retry_count < 0 or retry_count > MAX_RETRIES:
            raise ValueError("Invalid payment retry count")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        logger.warning(
            "Rejecting malformed payment message: error_type=%s",
            type(error).__name__,
        )
        raise RejectMessage(requeue=False) from error

    try:
        async with payment_processing_service() as service:
            payment = await service.process(payment_id)
    except (PaymentNotFoundError, PermanentWebhookDeliveryError) as error:
        logger.warning(
            "Rejecting payment: payment_id=%s error_type=%s",
            payment_id,
            type(error).__name__,
        )
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
            logger.error(
                "Retry limit reached: payment_id=%s error_type=%s",
                payment_id,
                type(error).__name__,
            )
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
        logger.warning(
            "Scheduled payment retry: payment_id=%s retry_count=%s error_type=%s",
            payment_id,
            retry_count + 1,
            type(error).__name__,
        )
        return
    except Exception as error:
        logger.error(
            "Rejecting unexpected processing error: payment_id=%s error_type=%s",
            payment_id,
            type(error).__name__,
        )
        raise RejectMessage(requeue=False) from error

    logger.info("Payment processed: payment_id=%s status=%s", payment.id, payment.status)
