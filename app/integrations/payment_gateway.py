import asyncio
import random

from app.domain.payment import Payment, PaymentStatus


class SimulatedPaymentGateway:
    async def process(self, payment: Payment) -> PaymentStatus:
        await asyncio.sleep(random.uniform(2, 5))
        return PaymentStatus.SUCCEEDED if random.random() < 0.9 else PaymentStatus.FAILED
