import httpx

from app.domain.payment import Payment
from app.schemas.webhook import PaymentWebhookPayload
from app.services.errors import WebhookDeliveryError


class HttpxWebhookSender:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def send(self, payment: Payment) -> None:
        payload = PaymentWebhookPayload.model_validate(payment).model_dump(mode="json")
        try:
            response = await self.client.post(
                payment.webhook_url,
                json=payload,
                headers={"Idempotency-Key": payment.webhook_idempotency_key},
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise WebhookDeliveryError(
                f"Webhook delivery failed for payment {payment.id}"
            ) from error
