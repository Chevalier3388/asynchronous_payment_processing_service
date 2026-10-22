class PaymentNotFoundError(LookupError):
    """Сообщение ссылается на отсутствующий платёж."""


class WebhookDeliveryError(Exception):
    """Неудачная попытка доставки уведомления."""


class WebhookDeliveryExhaustedError(WebhookDeliveryError):
    """Попытки доставки уведомления исчерпаны."""
