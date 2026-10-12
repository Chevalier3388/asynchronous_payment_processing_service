from faststream.rabbit import RabbitBroker, RabbitQueue

from app.core.config import settings

broker = RabbitBroker(settings.rabbitmq_url)

payments_dlq = RabbitQueue("payments.dlq", durable=True)

payments_queue = RabbitQueue(
    "payments.new",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": payments_dlq.name,
    },
)
