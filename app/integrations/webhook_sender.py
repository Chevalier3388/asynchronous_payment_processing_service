import httpx

from app.domain.payment import Payment
from app.schemas.webhook import PaymentWebhookPayload
from app.services.errors import PermanentWebhookDeliveryError, WebhookDeliveryError


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
            if response.status_code >= 400 and response.status_code < 500:
                if response.status_code not in (408, 429):
                    raise PermanentWebhookDeliveryError(
                        f"Webhook recipient rejected payment {payment.id} "
                        f"with HTTP {response.status_code}"
                    )
            response.raise_for_status()
        except PermanentWebhookDeliveryError:
            raise
        except httpx.HTTPError as error:
            raise WebhookDeliveryError(
                f"Webhook delivery failed for payment {payment.id}"
            ) from error
