from faststream import FastStream

# Импорт регистрирует обработчик сообщений.
from app.consumers.payment_consumer import process_payment  # noqa: F401
from app.messaging.broker import broker

app = FastStream(broker)
