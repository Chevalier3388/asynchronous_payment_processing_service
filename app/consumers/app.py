from faststream import FastStream

from app.messaging.broker import broker
from app.consumers.payment_consumer import process_payment

app = FastStream(broker)