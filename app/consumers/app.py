from faststream import FastStream

# Импорт регистрирует обработчик сообщений.
from app.consumers.payment_consumer import process_payment  # noqa: F401
from app.messaging.broker import broker, payments_dlq

app = FastStream(broker)


@app.on_startup
async def declare_dlq() -> None:
    await broker.connect()
    await broker.declare_queue(payments_dlq)
