from faststream.rabbit import RabbitBroker, RabbitQueue

from app.core.config import settings

broker = RabbitBroker(settings.rabbitmq_url)

payments_dlq = RabbitQueue("payments.dlq", durable=True)

payments_retry_1s = RabbitQueue(
    "payments.retry.1s",
    durable=True,
    arguments={
        "x-message-ttl": 1_000,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": "payments.new",
    },
)

payments_retry_2s = RabbitQueue(
    "payments.retry.2s",
    durable=True,
    arguments={
        "x-message-ttl": 2_000,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": "payments.new",
    },
)

payments_queue = RabbitQueue(
    "payments.new",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": payments_dlq.name,
    },
)
