class PaymentNotFoundError(LookupError):
    """Сообщение ссылается на отсутствующий платёж."""


class PaymentGatewayError(Exception):
    """Временная ошибка при обработке платежа шлюзом."""


class WebhookDeliveryError(Exception):
    """Неудачная попытка доставки уведомления."""


class PermanentWebhookDeliveryError(WebhookDeliveryError):
    """Получатель вернул постоянную ошибку, которую нет смысла повторять."""
