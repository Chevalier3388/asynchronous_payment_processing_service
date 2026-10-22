import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from aio_pika import DeliveryMode, Message
from faststream.exceptions import RejectMessage
from pamqp.commands import Basic
from sqlalchemy.dialects import postgresql

from app.consumers import payment_consumer as consumer
from app.domain.payment import Payment, PaymentCurrency, PaymentStatus
from app.integrations.webhook_sender import HttpxWebhookSender
from app.messaging.broker import (
    payments_dlq,
    payments_queue,
    payments_retry_1s,
    payments_retry_2s,
)
from app.messaging.rabbitmq import RabbitMQ
from app.repositories.outbox_repository import OutboxRepository
from app.schemas.payment import PaymentCreate
from app.services.errors import (
    PaymentNotFoundError,
    PermanentWebhookDeliveryError,
    WebhookDeliveryError,
)
from app.services.payment_service import PaymentService
from app.workers import outbox_publisher

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("scenario", ["new", "repeat", "conflict"])
async def test_payment_creation_and_outbox(payment, payment_payload, scenario):
    repository = SimpleNamespace(
        get_by_idempotency_key=AsyncMock(
            side_effect=[payment] if scenario == "repeat" else [None, payment]
        ),
        create_if_absent=AsyncMock(return_value=None if scenario == "conflict" else payment),
    )
    outbox = SimpleNamespace(create=AsyncMock())
    service = PaymentService(repository, outbox)

    result = await service.create_payment(PaymentCreate(**payment_payload), payment.idempotency_key)

    assert result is payment
    if scenario == "new":
        repository.create_if_absent.assert_awaited_once()
        candidate = repository.create_if_absent.await_args.args[0]
        assert candidate.amount == payment.amount
        assert candidate.idempotency_key == payment.idempotency_key
        outbox.create.assert_awaited_once()
        event = outbox.create.await_args.args[0]
        assert event.event_type == "payments.new"
        assert event.payload == {"payment_id": str(payment.id)}
    else:
        outbox.create.assert_not_awaited()
        if scenario == "repeat":
            repository.create_if_absent.assert_not_awaited()
        else:
            repository.create_if_absent.assert_awaited_once()
            assert repository.get_by_idempotency_key.await_count == 2


@pytest.mark.parametrize("publication_fails", [False, True])
async def test_outbox_is_marked_only_after_success(monkeypatch, payment, publication_fails):
    event = SimpleNamespace(
        id=payment.id, event_type="payments.new", payload={"payment_id": str(payment.id)}
    )
    repository = SimpleNamespace(
        get_unpublished=AsyncMock(return_value=[event]),
        mark_as_published=AsyncMock(),
    )
    monkeypatch.setattr(outbox_publisher, "OutboxRepository", lambda session: repository)

    async def publish(message, routing_key):
        repository.mark_as_published.assert_not_awaited()
        assert routing_key == "payments.new"
        assert json.loads(message.body) == event.payload
        assert message.delivery_mode == DeliveryMode.PERSISTENT
        if publication_fails:
            raise ConnectionError("Broker unavailable")

    rabbitmq = SimpleNamespace(publish=AsyncMock(side_effect=publish))
    publisher = outbox_publisher.OutboxPublisher(session=None, rabbitmq=rabbitmq)
    if publication_fails:
        with pytest.raises(ConnectionError):
            await publisher.publish_once()
        repository.mark_as_published.assert_not_awaited()
    else:
        await publisher.publish_once()
        repository.mark_as_published.assert_awaited_once_with(event.id)
    rabbitmq.publish.assert_awaited_once()


async def test_outbox_selection_uses_skip_locked():
    session = AsyncMock()
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
    session.execute.return_value = result

    await OutboxRepository(session).get_unpublished(limit=10)

    sql = str(session.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql


def _message(payment, retry_count=0, body=None):
    return SimpleNamespace(
        body=body or json.dumps({"payment_id": str(payment.id)}).encode(),
        headers={consumer.RETRY_HEADER: retry_count},
    )


def _mock_processing_service(monkeypatch, service):
    @asynccontextmanager
    async def provide_service():
        yield service

    monkeypatch.setattr(consumer, "payment_processing_service", provide_service)


async def test_consumer_processes_payment(monkeypatch, payment):
    service = SimpleNamespace(process=AsyncMock(return_value=payment))
    _mock_processing_service(monkeypatch, service)

    await consumer.process_payment(_message(payment))

    service.process.assert_awaited_once_with(payment.id)


@pytest.mark.parametrize(
    ("retry_count", "retry_queue"), [(0, payments_retry_1s), (1, payments_retry_2s)]
)
async def test_consumer_sends_transient_error_to_retry_queue(
    monkeypatch, payment, retry_count, retry_queue
):
    service = SimpleNamespace(process=AsyncMock(side_effect=WebhookDeliveryError()))
    _mock_processing_service(monkeypatch, service)
    publish = AsyncMock(return_value=Basic.Ack())
    monkeypatch.setattr(consumer.broker, "publish", publish)
    message = _message(payment, retry_count)

    await consumer.process_payment(message)

    publish.assert_awaited_once_with(
        message.body,
        queue=retry_queue,
        headers={consumer.RETRY_HEADER: retry_count + 1},
        content_type="application/json",
        persist=True,
    )


async def test_consumer_requires_retry_publish_ack(monkeypatch, payment):
    service = SimpleNamespace(process=AsyncMock(side_effect=WebhookDeliveryError()))
    _mock_processing_service(monkeypatch, service)
    monkeypatch.setattr(consumer.broker, "publish", AsyncMock(return_value=Basic.Nack()))

    with pytest.raises(RuntimeError, match="did not confirm"):
        await consumer.process_payment(_message(payment))


async def test_consumer_rejects_after_retry_limit(monkeypatch, payment):
    service = SimpleNamespace(process=AsyncMock(side_effect=WebhookDeliveryError()))
    _mock_processing_service(monkeypatch, service)
    publish = AsyncMock()
    monkeypatch.setattr(consumer.broker, "publish", publish)

    with pytest.raises(RejectMessage) as error:
        await consumer.process_payment(_message(payment, consumer.MAX_RETRIES))

    assert error.value.extra_options == {"requeue": False}
    publish.assert_not_awaited()
    assert payments_queue.arguments["x-dead-letter-routing-key"] == payments_dlq.name


@pytest.mark.parametrize("body", [b"not-json", b"{}", b'{"payment_id":"bad-uuid"}'])
async def test_consumer_rejects_malformed_message(monkeypatch, payment, body):
    factory = AsyncMock()
    monkeypatch.setattr(consumer, "payment_processing_service", factory)

    with pytest.raises(RejectMessage) as error:
        await consumer.process_payment(_message(payment, body=body))

    assert error.value.extra_options == {"requeue": False}
    factory.assert_not_awaited()


@pytest.mark.parametrize("error_type", [PaymentNotFoundError, PermanentWebhookDeliveryError])
async def test_consumer_sends_permanent_errors_to_dlq(monkeypatch, payment, error_type):
    service = SimpleNamespace(process=AsyncMock(side_effect=error_type()))
    _mock_processing_service(monkeypatch, service)
    publish = AsyncMock()
    monkeypatch.setattr(consumer.broker, "publish", publish)

    with pytest.raises(RejectMessage) as error:
        await consumer.process_payment(_message(payment))

    assert error.value.extra_options == {"requeue": False}
    publish.assert_not_awaited()


@pytest.mark.parametrize("confirmed", [True, False])
async def test_publication_requires_broker_ack(confirmed):
    rabbitmq = RabbitMQ()
    publish = AsyncMock(return_value=Basic.Ack() if confirmed else Basic.Nack())
    rabbitmq.channel = SimpleNamespace(default_exchange=SimpleNamespace(publish=publish))
    message = Message(body=b"test")

    if confirmed:
        await rabbitmq.publish(message, "payments.new")
    else:
        with pytest.raises(RuntimeError, match="did not confirm"):
            await rabbitmq.publish(message, "payments.new")

    publish.assert_awaited_once_with(
        message, routing_key="payments.new", mandatory=True, timeout=10
    )


async def test_payment_processing_time_is_utc(payment):
    domain_payment = Payment(
        id=payment.id,
        amount=payment.amount,
        currency=PaymentCurrency.RUB,
        description=payment.description,
        metadata=payment.metadata,
        idempotency_key=payment.idempotency_key,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
    )
    before = datetime.now(UTC)

    completed = domain_payment.complete(PaymentStatus.SUCCEEDED)

    assert completed.status is PaymentStatus.SUCCEEDED
    assert completed.processed_at.tzinfo is UTC
    assert before <= completed.processed_at <= datetime.now(UTC)


async def test_processing_service_persists_and_skips_delivered_webhook(payment):
    from app.services.payment_processing_service import PaymentProcessingService

    stored = Payment(
        id=payment.id,
        amount=payment.amount,
        currency=PaymentCurrency.RUB,
        description=payment.description,
        metadata=payment.metadata,
        idempotency_key=payment.idempotency_key,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
    )

    class Repository:
        async def get_by_id_for_update(self, payment_id):
            return stored

        async def save(self, updated):
            nonlocal stored
            stored = updated
            return stored

    commits = 0

    async def commit():
        nonlocal commits
        commits += 1

    gateway = SimpleNamespace(process=AsyncMock(return_value=PaymentStatus.SUCCEEDED))

    async def send(completed):
        assert commits == 1
        assert completed.status is PaymentStatus.SUCCEEDED

    sender = SimpleNamespace(send=AsyncMock(side_effect=send))
    service = PaymentProcessingService(Repository(), gateway, sender, commit)

    first = await service.process(stored.id)
    second = await service.process(stored.id)

    assert first.webhook_delivered_at is not None
    assert second.webhook_delivered_at == first.webhook_delivered_at
    assert commits == 4
    gateway.process.assert_awaited_once()
    sender.send.assert_awaited_once()


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (200, None),
        (400, PermanentWebhookDeliveryError),
        (408, WebhookDeliveryError),
        (429, WebhookDeliveryError),
        (500, WebhookDeliveryError),
    ],
)
async def test_webhook_sender_classifies_http_errors(payment, status_code, error_type):
    from app.domain.payment import Payment as DomainPayment

    domain_payment = DomainPayment(
        id=payment.id,
        amount=payment.amount,
        currency=PaymentCurrency.RUB,
        description=payment.description,
        metadata=payment.metadata,
        idempotency_key=payment.idempotency_key,
        webhook_url=payment.webhook_url,
        status=PaymentStatus.SUCCEEDED,
        created_at=payment.created_at,
        processed_at=payment.created_at,
    )
    response = httpx.Response(
        status_code,
        request=httpx.Request("POST", domain_payment.webhook_url),
    )
    client = AsyncMock()
    client.post.return_value = response
    sender = HttpxWebhookSender(client)

    if error_type is None:
        await sender.send(domain_payment)
    else:
        with pytest.raises(error_type):
            await sender.send(domain_payment)

    kwargs = client.post.await_args.kwargs
    assert kwargs["headers"] == {"Idempotency-Key": domain_payment.webhook_idempotency_key}
    assert kwargs["json"]["payment_id"] == str(domain_payment.id)


async def test_consumer_logs_without_logging_payload(monkeypatch, payment, caplog):
    from app.services.errors import PaymentNotFoundError

    _mock_processing_service(
        monkeypatch,
        SimpleNamespace(process=AsyncMock(side_effect=PaymentNotFoundError("sensitive detail"))),
    )
    message = _message(payment, body=b'{"payment_id":"' + str(payment.id).encode() + b'"}')

    with pytest.raises(RejectMessage):
        await consumer.process_payment(message)

    assert "payment_id=" in caplog.text
    assert "sensitive detail" not in caplog.text
    assert message.body.decode() not in caplog.text
