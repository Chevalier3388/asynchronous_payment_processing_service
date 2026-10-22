from faststream import FastStream

# Импорт регистрирует обработчик сообщений.
from app.consumers.payment_consumer import process_payment  # noqa: F401
from app.messaging.broker import (
    broker,
    payments_dlq,
    payments_retry_1s,
    payments_retry_2s,
)

app = FastStream(broker)


@app.on_startup
async def declare_processing_queues() -> None:
    await broker.connect()
    await broker.declare_queue(payments_dlq)
    await broker.declare_queue(payments_retry_1s)
    await broker.declare_queue(payments_retry_2s)
